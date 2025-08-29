from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Optional, Dict, List, Any
import logging
from app.config import settings
from app.core.k8s_tcp_proxy import K8sTCPProxyManager

logger = logging.getLogger(__name__)

class K8sIngressManager:
    """Manage Kubernetes Ingress resources for VNC access"""
    
    def __init__(self, k8s_manager):
        self.k8s = k8s_manager
        self.networking_v1 = client.NetworkingV1Api()
        self.v1 = client.CoreV1Api()
        self.tcp_proxy = K8sTCPProxyManager(k8s_manager)
        
    def create_pod_service(self, user_id: str) -> client.V1Service:
        """
        Create a ClusterIP Service for the VNC Pod (for Ingress backend)
        
        Args:
            user_id: User identifier
        
        Returns:
            Created Service object
        """
        service_name = f"vnc-service-{user_id}"
        namespace = settings.k8s_namespace_pods
        
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=namespace,
                labels={
                    "app": "vnc",
                    "user": user_id,
                    "managed-by": "vnc-manager"
                }
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",  # Use ClusterIP for Ingress
                selector={
                    "app": "vnc",
                    "user": user_id
                },
                ports=[
                    client.V1ServicePort(
                        name="vnc",
                        port=5901,
                        target_port=5901,
                        protocol="TCP"
                    ),
                    client.V1ServicePort(
                        name="novnc",
                        port=6080,
                        target_port=6080,
                        protocol="TCP"
                    ),
                    client.V1ServicePort(
                        name="ssh",
                        port=22,
                        target_port=22,
                        protocol="TCP"
                    )
                ]
            )
        )
        
        try:
            response = self.v1.create_namespaced_service(
                namespace=namespace,
                body=service
            )
            logger.info(f"Created ClusterIP service {service_name}")
            return response
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Service {service_name} already exists")
                return self.v1.read_namespaced_service(service_name, namespace)
            logger.error(f"Failed to create service {service_name}: {e}")
            raise
    
    def create_pod_ingress(self, user_id: str, domain: str = "vnc.service.thinkgs.cn") -> client.V1Ingress:
        """
        Create an Ingress for VNC/noVNC access
        
        Args:
            user_id: User identifier
            domain: Base domain for the ingress
        
        Returns:
            Created Ingress object
        """
        ingress_name = f"vnc-ingress-{user_id}"
        namespace = settings.k8s_namespace_pods
        service_name = f"vnc-service-{user_id}"
        
        # Create Ingress with WebSocket support
        ingress = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=ingress_name,
                namespace=namespace,
                labels={
                    "app": "vnc",
                    "user": user_id,
                    "managed-by": "vnc-manager"
                },
                annotations={
                    # Nginx Ingress annotations
                    "nginx.ingress.kubernetes.io/proxy-body-size": "0",
                    "nginx.ingress.kubernetes.io/proxy-read-timeout": "3600",
                    "nginx.ingress.kubernetes.io/proxy-send-timeout": "3600",
                    "nginx.ingress.kubernetes.io/proxy-connect-timeout": "3600",
                    
                    # Path rewrite to strip the user prefix
                    "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                    
                    # WebSocket support for noVNC
                    "nginx.ingress.kubernetes.io/websocket-services": service_name,
                    "nginx.ingress.kubernetes.io/upstream-hash-by": "$remote_addr",
                    
                    # SSL redirect (if using HTTPS)
                    "nginx.ingress.kubernetes.io/ssl-redirect": "false",
                    
                    # CORS settings for web access
                    "nginx.ingress.kubernetes.io/enable-cors": "true",
                    "nginx.ingress.kubernetes.io/cors-allow-origin": "*",
                    "nginx.ingress.kubernetes.io/cors-allow-methods": "GET, POST, OPTIONS",
                    "nginx.ingress.kubernetes.io/cors-allow-headers": "DNT,X-CustomHeader,Keep-Alive,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Authorization",
                    
                    # Rewrite for different services
                    "nginx.ingress.kubernetes.io/use-regex": "true",
                    
                    # Session affinity for consistent routing
                    "nginx.ingress.kubernetes.io/affinity": "cookie",
                    "nginx.ingress.kubernetes.io/affinity-mode": "persistent",
                    "nginx.ingress.kubernetes.io/session-cookie-name": f"vnc-session-{user_id}",
                    "nginx.ingress.kubernetes.io/session-cookie-max-age": "86400"
                }
            ),
            spec=client.V1IngressSpec(
                ingress_class_name="nginx",
                rules=[
                    client.V1IngressRule(
                        host=domain,
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                # noVNC web interface path with regex capture
                                client.V1HTTPIngressPath(
                                    path=f"/user/{user_id}/novnc(/|$)(.*)",
                                    path_type="ImplementationSpecific",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=client.V1ServiceBackendPort(
                                                number=6080
                                            )
                                        )
                                    )
                                ),
                                # WebSocket path for noVNC with regex capture
                                client.V1HTTPIngressPath(
                                    path=f"/user/{user_id}/websockify(/|$)(.*)",
                                    path_type="ImplementationSpecific",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=client.V1ServiceBackendPort(
                                                number=6080
                                            )
                                        )
                                    )
                                ),
                                # Direct VNC access (if needed) with regex capture
                                client.V1HTTPIngressPath(
                                    path=f"/user/{user_id}/vnc(/|$)(.*)",
                                    path_type="ImplementationSpecific",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=client.V1ServiceBackendPort(
                                                number=5901
                                            )
                                        )
                                    )
                                ),
                                # Generic path for all other resources under user directory
                                client.V1HTTPIngressPath(
                                    path=f"/user/{user_id}(/|$)(.*)",
                                    path_type="ImplementationSpecific",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name,
                                            port=client.V1ServiceBackendPort(
                                                number=6080
                                            )
                                        )
                                    )
                                )
                            ]
                        )
                    )
                ]
            )
        )
        
        try:
            response = self.networking_v1.create_namespaced_ingress(
                namespace=namespace,
                body=ingress
            )
            logger.info(f"Created Ingress {ingress_name} for user {user_id}")
            return response
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Ingress {ingress_name} already exists")
                return self.networking_v1.read_namespaced_ingress(ingress_name, namespace)
            logger.error(f"Failed to create Ingress {ingress_name}: {e}")
            raise
    
    def delete_pod_ingress(self, user_id: str):
        """Delete the Ingress and SSH proxy for a user's pod"""
        ingress_name = f"vnc-ingress-{user_id}"
        namespace = settings.k8s_namespace_pods
        
        try:
            # Delete HTTP Ingress
            self.networking_v1.delete_namespaced_ingress(
                name=ingress_name,
                namespace=namespace
            )
            logger.info(f"Deleted Ingress {ingress_name}")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Ingress {ingress_name} not found")
            else:
                raise
        
        # Remove SSH TCP proxy
        try:
            self.tcp_proxy.remove_ssh_proxy(user_id)
        except Exception as e:
            logger.warning(f"Failed to remove SSH proxy for user {user_id}: {e}")
    
    def get_pod_access_info(self, user_id: str, domain: str = "vnc.service.thinkgs.cn", vnc_password: str = None) -> Dict[str, Any]:
        """
        Get access information for a user's pod with both VNC and SSH access
        
        Args:
            user_id: User identifier
            domain: Base domain
        
        Returns:
            Access information dictionary with VNC and SSH details
        """
        # Note: Using NodePort 80 and proper WebSocket path
        base_url = f"http://{domain}"
        
        # Get SSH proxy information
        ssh_info = self.tcp_proxy.add_ssh_proxy(user_id)
        
        # Build noVNC URL with optional password parameter for auto-login
        novnc_base_url = f"{base_url}/user/{user_id}/vnc.html?path=user/{user_id}/websockify"
        if vnc_password:
            # Add password parameter for auto-login
            # Note: The password will be URL encoded and passed as a parameter
            import urllib.parse
            encoded_password = urllib.parse.quote(vnc_password)
            novnc_url_with_auth = f"{novnc_base_url}&password={encoded_password}&autoconnect=true"
        else:
            novnc_url_with_auth = novnc_base_url
        
        return {
            "vnc": {
                "novnc_url": novnc_url_with_auth,
                "novnc_url_no_auth": novnc_base_url,  # URL without password for manual login
                "websocket_url": f"ws://{domain}/user/{user_id}/websockify",
                "vnc_direct_url": f"{base_url}/user/{user_id}/vnc",
                "access_instructions": f"Open the novnc_url in your browser for automatic login"
            },
            "ssh": {
                "port": ssh_info["ssh_port"],
                "domain": ssh_info["ssh_domain"],
                "command": ssh_info["ssh_command"],
                "url": ssh_info["ssh_url"],
                "access_instructions": f"Use: {ssh_info['ssh_command']}"
            },
            "credentials": {
                "username": "void",
                "password": vnc_password if vnc_password else "Use the password provided when creating the pod"
            }
        }
    
    def create_ssh_ingress(self, user_id: str, domain: str = "ssh.example.com") -> Optional[client.V1Ingress]:
        """
        Create TCP Ingress for SSH access (requires TCP Ingress support)
        Note: This requires special Nginx Ingress configuration with TCP services
        
        Args:
            user_id: User identifier
            domain: SSH domain
        
        Returns:
            Created Ingress or None if not supported
        """
        # TCP Ingress requires ConfigMap configuration in nginx-ingress
        # This is typically done by updating the tcp-services ConfigMap
        
        namespace = settings.k8s_namespace_pods
        service_name = f"vnc-service-{user_id}"
        
        # Check if TCP services ConfigMap exists
        try:
            tcp_cm = self.v1.read_namespaced_config_map(
                name="tcp-services",
                namespace="ingress-nginx"
            )
            
            if not tcp_cm.data:
                tcp_cm.data = {}
            
            # Allocate a port for SSH (this would need proper port management)
            ssh_port = 32000 + hash(user_id) % 1000  # Simple port allocation
            
            # Add entry for this user's SSH service
            tcp_cm.data[str(ssh_port)] = f"{namespace}/{service_name}:22"
            
            # Update the ConfigMap
            self.v1.patch_namespaced_config_map(
                name="tcp-services",
                namespace="ingress-nginx",
                body=tcp_cm
            )
            
            logger.info(f"Added TCP service mapping for SSH on port {ssh_port}")
            
            return {
                "ssh_port": ssh_port,
                "ssh_command": f"ssh -p {ssh_port} void@{domain}"
            }
            
        except ApiException as e:
            logger.warning(f"TCP Ingress not supported or configured: {e}")
            return None