from kubernetes import client, config
from kubernetes.client.rest import ApiException
from typing import Optional, Dict, List, Any
import logging
import random
from app.config import settings

logger = logging.getLogger(__name__)

class K8sManager:
    def __init__(self):
        try:
            if settings.k8s_in_cluster:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes config")
            else:
                config.load_kube_config()
                logger.info("Loaded local Kubernetes config")
        except Exception as e:
            logger.error(f"Failed to load Kubernetes config: {e}")
            raise
            
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        
        # Track allocated ports
        self._allocated_ports = set()
        self._refresh_allocated_ports()
    
    def _refresh_allocated_ports(self):
        """Refresh the list of allocated NodePorts"""
        try:
            services = self.v1.list_service_for_all_namespaces()
            for svc in services.items:
                if svc.spec.type == "NodePort" and svc.spec.ports:
                    for port in svc.spec.ports:
                        if port.node_port:
                            self._allocated_ports.add(port.node_port)
        except Exception as e:
            logger.error(f"Failed to refresh allocated ports: {e}")
    
    def _get_available_port(self, start: int, end: int) -> int:
        """Get an available NodePort in the specified range"""
        for _ in range(100):  # Try up to 100 times
            port = random.randint(start, end)
            if port not in self._allocated_ports:
                self._allocated_ports.add(port)
                return port
        raise Exception(f"No available ports in range {start}-{end}")
    
    def create_namespace_if_not_exists(self, namespace: str):
        """Create namespace if it doesn't exist"""
        try:
            self.v1.read_namespace(namespace)
            logger.info(f"Namespace {namespace} already exists")
        except ApiException as e:
            if e.status == 404:
                body = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace)
                )
                self.v1.create_namespace(body)
                logger.info(f"Created namespace {namespace}")
            else:
                raise
    
    def create_vnc_pod(self, user_id: str, token: str, api_token: str = None, resource_quota: Optional[Dict] = None) -> client.V1Pod:
        """Create a VNC Pod for a user"""
        pod_name = f"vnc-{user_id}"
        namespace = settings.k8s_namespace_pods
        
        # Generate VNC/SSH password from API token (last 12 characters)
        vnc_password = api_token[-12:] if api_token and len(api_token) >= 12 else token
        
        # Log token status
        if api_token:
            logger.info(f"Creating pod with VOID_SK_TOKEN: {api_token[:10]}... (length: {len(api_token)})")
            logger.info(f"VNC/SSH password set from API token: ***{vnc_password[-4:]}")
        else:
            logger.warning("Creating pod without VOID_SK_TOKEN, using default token for password")
        
        # Ensure namespace exists
        self.create_namespace_if_not_exists(namespace)
        
        # Use provided quota or defaults
        if not resource_quota:
            resource_quota = {}
        
        cpu_request = resource_quota.get("cpu_request", settings.default_cpu_request)
        cpu_limit = resource_quota.get("cpu_limit", settings.default_cpu_limit)
        memory_request = resource_quota.get("memory_request", settings.default_memory_request)
        memory_limit = resource_quota.get("memory_limit", settings.default_memory_limit)
        
        # Pod specification
        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                namespace=namespace,
                labels={
                    "app": "vnc",
                    "user": user_id,
                    "managed-by": "vnc-manager"
                },
                annotations={
                    "vnc-manager/token": token[:8],  # Store first 8 chars for reference
                    "vnc-manager/created-at": "now"
                }
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="vnc",
                        image=f"{settings.k8s_image_registry}/{settings.k8s_vnc_image}",
                        ports=[
                            client.V1ContainerPort(container_port=5901, name="vnc", protocol="TCP"),
                            client.V1ContainerPort(container_port=6080, name="novnc", protocol="TCP"),
                            client.V1ContainerPort(container_port=22, name="ssh", protocol="TCP")
                        ],
                        env=[
                            client.V1EnvVar(name="USER_ID", value=user_id),
                            client.V1EnvVar(name="VNC_PASSWORD", value=vnc_password),  # Use last 12 chars of API token or fallback
                            client.V1EnvVar(name="DISPLAY", value=":1"),
                            client.V1EnvVar(name="VNC_RESOLUTION", value="1920x1080"),
                            client.V1EnvVar(name="VNC_DEPTH", value="24")
                        ] + ([client.V1EnvVar(name="VOID_SK_TOKEN", value=api_token)] if api_token else []),  # Only add if token exists
                        resources=client.V1ResourceRequirements(
                            requests={
                                "cpu": cpu_request,
                                "memory": memory_request
                            },
                            limits={
                                "cpu": cpu_limit,
                                "memory": memory_limit
                            }
                        ),
                        volume_mounts=[
                            client.V1VolumeMount(
                                name="user-data",
                                mount_path="/home/void/workspace"
                            ),
                            client.V1VolumeMount(
                                name="shm",
                                mount_path="/dev/shm"
                            )
                        ],
                        security_context=client.V1SecurityContext(
                            capabilities=client.V1Capabilities(
                                add=["SYS_ADMIN"]
                            ),
                            run_as_user=0,
                            run_as_group=0,
                            allow_privilege_escalation=True
                        ),
                        liveness_probe=client.V1Probe(
                            tcp_socket=client.V1TCPSocketAction(port=5901),
                            initial_delay_seconds=30,
                            period_seconds=10,
                            timeout_seconds=5,
                            failure_threshold=3
                        ),
                        readiness_probe=client.V1Probe(
                            tcp_socket=client.V1TCPSocketAction(port=5901),
                            initial_delay_seconds=10,
                            period_seconds=5,
                            timeout_seconds=3,
                            failure_threshold=3
                        )
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="user-data",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=f"pvc-{user_id}"
                        )
                    ),
                    client.V1Volume(
                        name="shm",
                        empty_dir=client.V1EmptyDirVolumeSource(
                            medium="Memory",
                            size_limit="2Gi"
                        )
                    )
                ],
                restart_policy="Always",
                dns_policy="ClusterFirst",
                termination_grace_period_seconds=30
            )
        )
        
        try:
            response = self.v1.create_namespaced_pod(
                namespace=namespace,
                body=pod
            )
            logger.info(f"Created pod {pod_name} in namespace {namespace}")
            return response
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Pod {pod_name} already exists")
                return self.get_pod(pod_name, namespace)
            logger.error(f"Failed to create pod {pod_name}: {e}")
            raise
    
    def create_pvc(self, user_id: str, size: str = "10Gi") -> client.V1PersistentVolumeClaim:
        """Create a PersistentVolumeClaim for user data"""
        pvc_name = f"pvc-{user_id}"
        namespace = settings.k8s_namespace_pods
        
        pvc = client.V1PersistentVolumeClaim(
            metadata=client.V1ObjectMeta(
                name=pvc_name,
                namespace=namespace,
                labels={
                    "app": "vnc",
                    "user": user_id,
                    "managed-by": "vnc-manager"
                }
            ),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                storage_class_name="183nfs",  # Use the NFS storage class
                resources=client.V1ResourceRequirements(
                    requests={"storage": size}
                )
            )
        )
        
        try:
            response = self.v1.create_namespaced_persistent_volume_claim(
                namespace=namespace,
                body=pvc
            )
            logger.info(f"Created PVC {pvc_name} with size {size}")
            return response
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"PVC {pvc_name} already exists")
                return self.v1.read_namespaced_persistent_volume_claim(pvc_name, namespace)
            logger.error(f"Failed to create PVC {pvc_name}: {e}")
            raise
    
    def create_service(self, user_id: str) -> client.V1Service:
        """Create a Service to expose the VNC Pod"""
        service_name = f"vnc-service-{user_id}"
        namespace = settings.k8s_namespace_pods
        
        # Allocate NodePorts
        vnc_port = self._get_available_port(
            settings.vnc_port_range_start,
            settings.vnc_port_range_end
        )
        novnc_port = self._get_available_port(
            settings.vnc_port_range_start,
            settings.vnc_port_range_end
        )
        ssh_port = self._get_available_port(
            settings.ssh_port_range_start,
            settings.ssh_port_range_end
        )
        
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
                type="NodePort",
                selector={
                    "app": "vnc",
                    "user": user_id
                },
                ports=[
                    client.V1ServicePort(
                        name="vnc",
                        port=5901,
                        target_port=5901,
                        node_port=vnc_port,
                        protocol="TCP"
                    ),
                    client.V1ServicePort(
                        name="novnc",
                        port=6080,
                        target_port=6080,
                        node_port=novnc_port,
                        protocol="TCP"
                    ),
                    client.V1ServicePort(
                        name="ssh",
                        port=22,
                        target_port=22,
                        node_port=ssh_port,
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
            logger.info(f"Created service {service_name} with NodePorts: VNC={vnc_port}, noVNC={novnc_port}, SSH={ssh_port}")
            return response
        except ApiException as e:
            if e.status == 409:
                logger.warning(f"Service {service_name} already exists")
                return self.v1.read_namespaced_service(service_name, namespace)
            logger.error(f"Failed to create service {service_name}: {e}")
            raise
    
    def get_pod(self, pod_name: str, namespace: str = None) -> Optional[client.V1Pod]:
        """Get a Pod by name"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        try:
            return self.v1.read_namespaced_pod(pod_name, namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise
    
    def delete_pod(self, pod_name: str, namespace: str = None):
        """Delete a Pod"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        try:
            self.v1.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
                body=client.V1DeleteOptions(
                    grace_period_seconds=30
                )
            )
            logger.info(f"Deleted pod {pod_name}")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Pod {pod_name} not found")
            else:
                raise
    
    def delete_service(self, service_name: str, namespace: str = None):
        """Delete a Service"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        try:
            # Get service to free up NodePorts
            service = self.v1.read_namespaced_service(service_name, namespace)
            if service.spec.ports:
                for port in service.spec.ports:
                    if port.node_port and port.node_port in self._allocated_ports:
                        self._allocated_ports.remove(port.node_port)
            
            self.v1.delete_namespaced_service(
                name=service_name,
                namespace=namespace
            )
            logger.info(f"Deleted service {service_name}")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"Service {service_name} not found")
            else:
                raise
    
    def delete_pvc(self, pvc_name: str, namespace: str = None):
        """Delete a PersistentVolumeClaim"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        try:
            self.v1.delete_namespaced_persistent_volume_claim(
                name=pvc_name,
                namespace=namespace
            )
            logger.info(f"Deleted PVC {pvc_name}")
        except ApiException as e:
            if e.status == 404:
                logger.warning(f"PVC {pvc_name} not found")
            else:
                raise
    
    def get_pod_logs(self, pod_name: str, namespace: str = None, tail_lines: int = 100) -> str:
        """Get Pod logs"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        try:
            logs = self.v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines
            )
            return logs
        except ApiException as e:
            logger.error(f"Failed to get logs for pod {pod_name}: {e}")
            raise
    
    def get_pod_status(self, pod_name: str, namespace: str = None) -> Dict[str, Any]:
        """Get detailed Pod status"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        pod = self.get_pod(pod_name, namespace)
        if not pod:
            return None
        
        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "phase": pod.status.phase,
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message
                }
                for c in (pod.status.conditions or [])
            ],
            "container_statuses": [
                {
                    "name": cs.name,
                    "ready": cs.ready,
                    "restart_count": cs.restart_count,
                    "state": {
                        "running": cs.state.running.started_at if cs.state.running else None,
                        "waiting": cs.state.waiting.reason if cs.state.waiting else None,
                        "terminated": cs.state.terminated.reason if cs.state.terminated else None
                    }
                }
                for cs in (pod.status.container_statuses or [])
            ],
            "pod_ip": pod.status.pod_ip,
            "host_ip": pod.status.host_ip,
            "start_time": pod.status.start_time
        }
    
    def restart_pod(self, pod_name: str, namespace: str = None):
        """Restart a Pod by deleting and recreating it"""
        if not namespace:
            namespace = settings.k8s_namespace_pods
        
        # Get current pod configuration
        pod = self.get_pod(pod_name, namespace)
        if not pod:
            raise Exception(f"Pod {pod_name} not found")
        
        # Extract user_id from labels
        user_id = pod.metadata.labels.get("user")
        if not user_id:
            raise Exception(f"Cannot determine user_id for pod {pod_name}")
        
        # Generate new VNC password for restart
        import secrets
        token = secrets.token_urlsafe(6)[:8]
        
        # Delete the pod
        self.delete_pod(pod_name, namespace)
        
        # Wait a moment for cleanup
        import time
        time.sleep(2)
        
        # Recreate the pod (no API token on restart)
        return self.create_vnc_pod(user_id, token, api_token=None)