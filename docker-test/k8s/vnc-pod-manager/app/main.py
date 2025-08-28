from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
import logging
import json
import uvicorn
from contextlib import asynccontextmanager

from app.config import settings
from app.core.k8s_client import K8sManager
from app.core.k8s_ingress import K8sIngressManager
from app.core.k8s_tcp_proxy import K8sTCPProxyManager
from app.core.redis_lock import RedisLock, RedisConnectionPool
from app.core.token_manager import TokenManager
from app.api.v1 import pods, health, monitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
k8s_manager = None
ingress_manager = None
tcp_proxy_manager = None
redis_client = None
token_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global k8s_manager, ingress_manager, tcp_proxy_manager, redis_client, token_manager
    
    # Startup
    logger.info("Starting VNC Pod Manager API")
    
    # Initialize K8s client
    k8s_manager = K8sManager()
    ingress_manager = K8sIngressManager(k8s_manager)
    tcp_proxy_manager = K8sTCPProxyManager(k8s_manager)
    
    # Initialize Redis client
    redis_client = RedisConnectionPool.get_client(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password
    )
    
    # Initialize Token Manager
    token_manager = TokenManager(redis_client=redis_client)
    
    # Ensure namespaces exist
    k8s_manager.create_namespace_if_not_exists(settings.k8s_namespace_pods)
    
    logger.info("VNC Pod Manager API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down VNC Pod Manager API")
    if redis_client:
        redis_client.close()

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Kubernetes VNC Pod Dynamic Management System",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",  # Allow all origins for development
        "http://localhost:*",
        "http://127.0.0.1:*", 
        "file://*",  # Allow file:// protocol for local HTML files
        "null"  # Allow null origin for local HTML files
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "*",
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "Origin",
        "X-CSRFToken"
    ],
    expose_headers=["*"]
)

# Add middleware to handle preflight OPTIONS requests
@app.middleware("http")
async def cors_handler(request: Request, call_next):
    """Handle CORS preflight requests"""
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400"
            }
        )
    
    response = await call_next(request)
    
    # Add CORS headers to all responses
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "*"
    
    return response

# Dependency to get authenticated user from token
async def get_current_user(authorization: str = Header(None)):
    """Extract and validate user from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    # Support both "Bearer token" and direct token
    token = authorization
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    
    # Check if token is blacklisted
    if token_manager.is_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked")
    
    # Validate token
    user_info = token_manager.validate_token(token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return user_info

# API Routes
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "endpoints": {
            "health": "/health",
            "ready": "/ready",
            "metrics": "/metrics",
            "api_docs": "/docs",
            "pods": "/api/v1/pods"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint"""
    try:
        # Check Redis connection
        redis_client.ping()
        # Check K8s API access
        k8s_manager.v1.list_namespace(limit=1)
        return {"status": "ready"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")

@app.post("/api/v1/pods")
async def create_pod(
    background_tasks: BackgroundTasks,
    user_info: dict = Depends(get_current_user),
    resource_quota: Optional[Dict[str, str]] = None
):
    """
    Create a VNC Pod for the authenticated user
    
    - **Authorization**: Required (Bearer token or direct token)
    - **resource_quota**: Optional resource limits override
    """
    user_id = user_info["user_id"]
    # Generate a VNC password for this pod
    vnc_password = token_manager.generate_pod_specific_token(user_id)
    
    try:
        # Check if pod already exists
        existing_pod = k8s_manager.get_pod(f"vnc-{user_id}")
        if existing_pod and existing_pod.status.phase in ["Running", "Pending"]:
            # Get access info
            access_info = ingress_manager.get_pod_access_info(user_id, settings.vnc_domain)
            return {
                "status": "exists",
                "message": "Pod already exists and is running",
                "pod_name": f"vnc-{user_id}",
                "access_info": access_info
            }
        
        # Use distributed lock to prevent concurrent creation
        lock = RedisLock(redis_client, f"create_pod_{user_id}", timeout=30)
        
        with lock.acquire_context():
            # Double-check after acquiring lock
            existing_pod = k8s_manager.get_pod(f"vnc-{user_id}")
            if existing_pod and existing_pod.status.phase in ["Running", "Pending"]:
                access_info = ingress_manager.get_pod_access_info(user_id, settings.vnc_domain)
                return {
                    "status": "exists",
                    "message": "Pod already exists",
                    "pod_name": f"vnc-{user_id}",
                    "access_info": access_info
                }
            
            # Extract resource quota from token or use provided
            if not resource_quota:
                resource_quota = user_info.get("resource_quota", {})
            
            # Create PVC for user data
            pvc = k8s_manager.create_pvc(
                user_id=user_id,
                size=resource_quota.get("storage", settings.default_storage_size)
            )
            
            # Get the actual user token from database using user_info
            # user_info contains db_user_id which is the actual integer ID in database
            from app.core.database import get_db_manager
            db_manager = get_db_manager()
            
            # Get user's actual token from database
            db_user_id = user_info.get("db_user_id")
            if db_user_id:
                api_token = db_manager.get_user_token_by_id(db_user_id)
                if api_token:
                    logger.info(f"Retrieved user token from database for user ID: {db_user_id}")
                    logger.info(f"Token length: {len(api_token)}, starts with: {api_token[:10]}...")
                else:
                    logger.warning(f"Could not retrieve token from database for user ID: {db_user_id}")
                    api_token = None
            else:
                logger.warning("No db_user_id found in user_info")
                logger.warning(f"user_info keys: {user_info.keys()}")
                api_token = None
            
            # Create the VNC Pod with VNC password and API token
            pod = k8s_manager.create_vnc_pod(
                user_id=user_id,
                token=vnc_password,  # Use generated VNC password
                api_token=api_token,  # Pass API token for void (from database)
                resource_quota=resource_quota
            )
            
            # Create ClusterIP Service
            service = ingress_manager.create_pod_service(user_id)
            
            # Create Ingress for web access
            ingress = ingress_manager.create_pod_ingress(
                user_id=user_id,
                domain=settings.vnc_domain
            )
            
            # Add SSH proxy configuration
            ssh_info = tcp_proxy_manager.add_ssh_proxy(user_id)
            
            # Get access information
            access_info = ingress_manager.get_pod_access_info(user_id, settings.vnc_domain)
            # Add SSH info to access_info
            access_info["ssh"] = ssh_info
            
            # Store pod info in Redis
            pod_info = {
                "pod_name": pod.metadata.name,
                "user_id": user_id,
                "created_at": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
                "service_name": service.metadata.name,
                "ingress_name": ingress.metadata.name,
                "access_info": access_info,
                "vnc_password": vnc_password  # Include VNC password in cache
            }
            redis_client.setex(
                f"pod:{user_id}",
                86400,  # Cache for 24 hours
                json.dumps(pod_info)
            )
            
            logger.info(f"Successfully created pod for user {user_id}")
            
            return {
                "status": "created",
                "message": "Pod created successfully",
                "pod_name": pod.metadata.name,
                "access_info": access_info,
                "vnc_password": vnc_password  # Return VNC password to user
            }
            
    except Exception as e:
        logger.error(f"Failed to create pod for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/pods/{pod_name}")
async def delete_pod(
    pod_name: str,
    user_info: dict = Depends(get_current_user)
):
    """
    Delete a VNC Pod
    
    - **pod_name**: Name of the pod to delete
    - **Authorization**: Required
    """
    user_id = user_info["user_id"]
    
    # Verify pod ownership
    if not pod_name.endswith(f"-{user_id}"):
        raise HTTPException(status_code=403, detail="Not authorized to delete this pod")
    
    try:
        # Use distributed lock (90 seconds to account for pod termination wait)
        lock = RedisLock(redis_client, f"delete_pod_{user_id}", timeout=90)
        
        with lock.acquire_context():
            # Delete Ingress
            ingress_manager.delete_pod_ingress(user_id)
            
            # Delete Service
            k8s_manager.delete_service(f"vnc-service-{user_id}")
            
            # Delete Pod
            k8s_manager.delete_pod(pod_name)
            
            # Wait for pod to be completely deleted (max 60 seconds)
            import time
            max_wait = 60
            wait_interval = 2
            elapsed = 0
            
            while elapsed < max_wait:
                pod = k8s_manager.get_pod(pod_name)
                if not pod:
                    # Pod is completely deleted
                    logger.info(f"Pod {pod_name} fully terminated after {elapsed} seconds")
                    break
                    
                logger.info(f"Waiting for pod {pod_name} to terminate... (status: {pod.status.phase})")
                time.sleep(wait_interval)
                elapsed += wait_interval
            else:
                logger.warning(f"Pod {pod_name} still terminating after {max_wait} seconds, proceeding anyway")
            
            # Note: SSH proxy removal is already handled in ingress_manager.delete_pod_ingress()
            # which was called above, so we don't need to call it again here
            
            # Optionally keep PVC for data persistence
            # k8s_manager.delete_pvc(f"pvc-{user_id}")
            
            # Clear Redis cache
            redis_client.delete(f"pod:{user_id}")
            
            logger.info(f"Successfully deleted pod {pod_name}")
            
            return {
                "status": "deleted",
                "message": "Pod deleted successfully",
                "pod_name": pod_name
            }
            
    except Exception as e:
        logger.error(f"Failed to delete pod {pod_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/pods/{pod_name}")
async def get_pod_status(
    pod_name: str,
    user_info: dict = Depends(get_current_user)
):
    """
    Get pod status and details
    
    - **pod_name**: Name of the pod
    - **Authorization**: Required
    """
    user_id = user_info["user_id"]
    
    # Verify pod ownership
    if not pod_name.endswith(f"-{user_id}"):
        raise HTTPException(status_code=403, detail="Not authorized to access this pod")
    
    try:
        status = k8s_manager.get_pod_status(pod_name)
        if not status:
            raise HTTPException(status_code=404, detail="Pod not found")
        
        # Add access info
        access_info = ingress_manager.get_pod_access_info(user_id, settings.vnc_domain)
        status["access_info"] = access_info
        
        return status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get pod status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/pods/{pod_name}/restart")
async def restart_pod(
    pod_name: str,
    user_info: dict = Depends(get_current_user)
):
    """
    Restart a VNC Pod
    
    - **pod_name**: Name of the pod to restart
    - **Authorization**: Required
    """
    user_id = user_info["user_id"]
    
    # Verify pod ownership
    if not pod_name.endswith(f"-{user_id}"):
        raise HTTPException(status_code=403, detail="Not authorized to restart this pod")
    
    try:
        # Use distributed lock
        lock = RedisLock(redis_client, f"restart_pod_{user_id}", timeout=30)
        
        with lock.acquire_context():
            # Get current pod info
            pod = k8s_manager.get_pod(pod_name)
            if not pod:
                raise HTTPException(status_code=404, detail="Pod not found")
            
            # Delete the pod (it will be recreated by deployment/replicaset if configured)
            k8s_manager.delete_pod(pod_name)
            
            # Wait a moment
            import time
            time.sleep(2)
            
            # Generate new VNC password
            new_vnc_password = token_manager.generate_pod_specific_token(user_id)
            
            # Recreate the pod
            new_pod = k8s_manager.create_vnc_pod(
                user_id=user_id,
                token=new_vnc_password,
                resource_quota=user_info.get("resource_quota", {})
            )
            
            logger.info(f"Successfully restarted pod {pod_name}")
            
            return {
                "status": "restarted",
                "message": "Pod restarted successfully",
                "old_pod_name": pod_name,
                "new_pod_name": new_pod.metadata.name
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restart pod {pod_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/pods/{pod_name}/logs")
async def get_pod_logs(
    pod_name: str,
    tail_lines: int = 100,
    user_info: dict = Depends(get_current_user)
):
    """
    Get pod logs
    
    - **pod_name**: Name of the pod
    - **tail_lines**: Number of lines to return from the end
    - **Authorization**: Required
    """
    user_id = user_info["user_id"]
    
    # Verify pod ownership
    if not pod_name.endswith(f"-{user_id}"):
        raise HTTPException(status_code=403, detail="Not authorized to access this pod")
    
    try:
        logs = k8s_manager.get_pod_logs(pod_name, tail_lines=tail_lines)
        return {
            "pod_name": pod_name,
            "logs": logs,
            "tail_lines": tail_lines
        }
        
    except Exception as e:
        logger.error(f"Failed to get pod logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/pods")
async def list_user_pods(user_info: dict = Depends(get_current_user)):
    """
    List all pods for the authenticated user
    
    - **Authorization**: Required
    """
    user_id = user_info["user_id"]
    
    try:
        # Get pods with user label
        pods = k8s_manager.v1.list_namespaced_pod(
            namespace=settings.k8s_namespace_pods,
            label_selector=f"user={user_id}"
        )
        
        pod_list = []
        for pod in pods.items:
            pod_info = {
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "created_at": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
                "pod_ip": pod.status.pod_ip,
                "host_ip": pod.status.host_ip
            }
            pod_list.append(pod_info)
        
        return {
            "user_id": user_id,
            "pods": pod_list,
            "count": len(pod_list)
        }
        
    except Exception as e:
        logger.error(f"Failed to list pods: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Import additional modules
import json
import prometheus_client
from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics
pod_creation_counter = Counter('vnc_pod_creations_total', 'Total number of pod creation attempts')
pod_deletion_counter = Counter('vnc_pod_deletions_total', 'Total number of pod deletion attempts')
active_pods_gauge = Gauge('vnc_active_pods', 'Number of active VNC pods')
api_request_duration = Histogram('vnc_api_request_duration_seconds', 'API request duration')

@app.get("/metrics")
async def get_metrics():
    """Prometheus metrics endpoint"""
    return prometheus_client.generate_latest()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )