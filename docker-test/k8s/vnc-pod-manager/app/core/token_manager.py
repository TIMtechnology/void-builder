"""Token management using MySQL database"""

from typing import Optional, Dict, Any, List
import hashlib
import logging
from datetime import datetime, timezone
import json
from app.config import settings
from app.core.database import get_db_manager

logger = logging.getLogger(__name__)

class TokenManager:
    """Token management for user authentication using MySQL database"""
    
    def __init__(self, redis_client=None):
        self.redis_client = redis_client
        self.db_manager = get_db_manager()
        # Token prefix for identification
        self.token_prefix = "sk-"
        
    def hash_token(self, token: str) -> str:
        """
        Hash a token for secure storage/caching
        
        Args:
            token: Plain text token
        
        Returns:
            SHA256 hash of the token
        """
        return hashlib.sha256(token.encode()).hexdigest()
    
    def validate_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate API token against MySQL database
        
        Args:
            token: API token (e.g., "sk-5Xqty9Vx3MiMSLp06eF585Aa01404f9f81594aB33a5360A3")
        
        Returns:
            User info dict if valid, None otherwise
        """
        if not token or not isinstance(token, str):
            logger.warning("Invalid token format: empty or not string")
            return None
        
        # Basic validation - check if starts with expected prefix
        if not token.startswith(self.token_prefix):
            logger.warning(f"Invalid token format: doesn't start with {self.token_prefix}")
            return None
        
        # Check blacklist first
        if self.is_blacklisted(token):
            logger.warning(f"Blacklisted token attempted: {token[:20]}...")
            return None
        
        # Hash the token for caching
        token_hash = self.hash_token(token)
        
        # Check Redis cache first
        if self.redis_client:
            try:
                cached_info = self.redis_client.get(f"token:{token_hash}")
                if cached_info:
                    logger.debug(f"Token found in cache")
                    user_info = json.loads(cached_info)
                    # Update last access
                    self.db_manager.update_user_last_access(user_info.get("user_id"))
                    return user_info
            except Exception as e:
                logger.error(f"Redis cache error: {e}")
        
        # Query MySQL database
        user_data = self.db_manager.get_user_by_token(token)
        
        if not user_data:
            logger.warning(f"Token not found in database: {token[:20]}...")
            return None
        
        # Build user info
        user_info = {
            "user_id": str(user_data["user_id"]),  # Convert to string for consistency
            "username": user_data.get("user_name", ""),  # Fixed field name from database
            "nickname": user_data.get("nick_name", ""),  # Fixed field name from database
            "token_hash": token_hash,
            "permissions": ["vnc", "ssh", "novnc"],  # Default permissions
            "resource_quota": self.db_manager.get_user_resource_quota(user_data["user_id"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_valid": True,
            "db_user_id": user_data["user_id"]  # Keep original int ID
        }
        
        # Cache the result in Redis
        if self.redis_client:
            try:
                self.redis_client.setex(
                    f"token:{token_hash}",
                    3600,  # Cache for 1 hour
                    json.dumps(user_info)
                )
                logger.debug(f"Cached token info for user: {user_info['username']}")
            except Exception as e:
                logger.error(f"Failed to cache token info: {e}")
        
        # Update last access time
        self.db_manager.update_user_last_access(user_data["user_id"])
        
        logger.info(f"Validated token for user: {user_info['username']} (ID: {user_info['user_id']})")
        return user_info
    
    def extract_user_id(self, token: str) -> Optional[str]:
        """
        Extract user_id from token
        
        Args:
            token: API token
        
        Returns:
            User ID if valid, None otherwise
        """
        user_info = self.validate_token(token)
        if user_info:
            return user_info.get("user_id")
        return None
    
    def extract_permissions(self, token: str) -> Optional[List[str]]:
        """
        Extract permissions from token
        
        Args:
            token: API token
        
        Returns:
            List of permissions if valid, None otherwise
        """
        user_info = self.validate_token(token)
        if user_info:
            return user_info.get("permissions", [])
        return None
    
    def extract_resource_quota(self, token: str) -> Optional[Dict[str, str]]:
        """
        Extract resource quota from token
        
        Args:
            token: API token
        
        Returns:
            Resource quota dict if valid, None otherwise
        """
        user_info = self.validate_token(token)
        if user_info:
            return user_info.get("resource_quota", {
                "cpu_request": settings.default_cpu_request,
                "cpu_limit": settings.default_cpu_limit,
                "memory_request": settings.default_memory_request,
                "memory_limit": settings.default_memory_limit,
                "storage": settings.default_storage_size
            })
        return None
    
    def has_permission(self, token: str, permission: str) -> bool:
        """
        Check if token has specific permission
        
        Args:
            token: API token
            permission: Permission to check
        
        Returns:
            True if has permission, False otherwise
        """
        permissions = self.extract_permissions(token)
        if permissions:
            return permission in permissions
        return False
    
    def generate_pod_specific_token(self, _user_id: str) -> str:
        """
        Generate a pod-specific token for internal use (VNC password, etc.)
        
        Args:
            _user_id: User identifier (unused but kept for compatibility)
        
        Returns:
            Short token for pod access
        """
        # Generate a simple 8-character token for VNC password
        import secrets
        return secrets.token_urlsafe(6)[:8]
    
    def invalidate_token(self, token: str) -> bool:
        """
        Invalidate a token (add to blacklist)
        Note: This only blacklists in Redis cache, not in database
        
        Args:
            token: API token to invalidate
        
        Returns:
            True if invalidated, False otherwise
        """
        if self.redis_client:
            try:
                token_hash = self.hash_token(token)
                # Add to blacklist
                self.redis_client.setex(
                    f"blacklist:{token_hash}",
                    86400 * 30,  # Blacklist for 30 days
                    "1"
                )
                # Remove from cache
                self.redis_client.delete(f"token:{token_hash}")
                logger.info(f"Token invalidated in cache: {token[:20]}...")
                return True
            except Exception as e:
                logger.error(f"Failed to invalidate token: {e}")
                return False
        return False
    
    def is_blacklisted(self, token: str) -> bool:
        """
        Check if token is blacklisted
        
        Args:
            token: API token
        
        Returns:
            True if blacklisted, False otherwise
        """
        if self.redis_client:
            try:
                token_hash = self.hash_token(token)
                return self.redis_client.exists(f"blacklist:{token_hash}") > 0
            except Exception as e:
                logger.error(f"Failed to check blacklist: {e}")
                return False
        return False
    
    def clear_token_cache(self, token: str) -> bool:
        """
        Clear token from cache
        
        Args:
            token: API token
        
        Returns:
            True if cleared, False otherwise
        """
        if self.redis_client:
            try:
                token_hash = self.hash_token(token)
                self.redis_client.delete(f"token:{token_hash}")
                logger.debug(f"Cleared cache for token: {token[:20]}...")
                return True
            except Exception as e:
                logger.error(f"Failed to clear token cache: {e}")
                return False
        return False