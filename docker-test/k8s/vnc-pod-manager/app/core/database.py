"""Database connection and operations"""

import pymysql
from pymysql.cursors import DictCursor
from typing import Optional, Dict, Any
import logging
from contextlib import contextmanager
from app.config import settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    """MySQL database manager for user authentication"""
    
    def __init__(self):
        self.connection_params = {
            'host': settings.mysql_host,
            'port': settings.mysql_port,
            'user': settings.mysql_user,
            'password': settings.mysql_password,
            'database': settings.mysql_database,
            'charset': 'utf8mb4',
            'cursorclass': DictCursor,
            'autocommit': True
        }
        self._connection = None
    
    @contextmanager
    def get_connection(self):
        """Get database connection context manager"""
        connection = None
        try:
            connection = pymysql.connect(**self.connection_params)
            yield connection
        except pymysql.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if connection:
                connection.close()
    
    @contextmanager
    def get_cursor(self):
        """Get database cursor context manager"""
        with self.get_connection() as connection:
            cursor = connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
    
    def get_user_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Get user information by API token
        
        Args:
            token: API token (e.g., "sk-5Xqty9Vx3MiMSLp06eF585Aa01404f9f81594aB33a5360A3")
        
        Returns:
            User information dict or None if not found
        """
        try:
            with self.get_cursor() as cursor:
                # Query im_user table for user with this token
                query = """
                    SELECT 
                        id as user_id,
                        user_name,
                        nick_name,
                        token_key,
                        is_banned,
                        created_time,
                        last_login_time
                    FROM im_user 
                    WHERE token_key = %s
                    AND is_banned = 0
                    LIMIT 1
                """
                
                cursor.execute(query, (token,))
                result = cursor.fetchone()
                
                if result:
                    logger.info(f"Found user for token: {result.get('user_name')}")
                    return result
                else:
                    logger.warning(f"No user found for token: {token[:20]}...")
                    return None
                    
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return None
    
    def get_user_token_by_id(self, user_id: int) -> Optional[str]:
        """
        Get user's API token by user ID
        
        Args:
            user_id: User ID
        
        Returns:
            API token string or None if not found
        """
        try:
            with self.get_cursor() as cursor:
                query = """
                    SELECT token_key
                    FROM im_user 
                    WHERE id = %s
                    AND is_banned = 0
                    LIMIT 1
                """
                
                cursor.execute(query, (user_id,))
                result = cursor.fetchone()
                
                if result and result.get('token_key'):
                    logger.info(f"Found token for user ID: {user_id}")
                    return result['token_key']
                else:
                    logger.warning(f"No token found for user ID: {user_id}")
                    return None
                    
        except pymysql.Error as e:
            logger.error(f"Database query error: {e}")
            return None
    
    def update_user_last_access(self, user_id: int) -> bool:
        """
        Update user's last access time
        
        Args:
            user_id: User ID
        
        Returns:
            True if updated successfully
        """
        try:
            with self.get_cursor() as cursor:
                query = """
                    UPDATE im_user 
                    SET last_login_time = NOW() 
                    WHERE id = %s
                """
                cursor.execute(query, (user_id,))
                return True
                
        except pymysql.Error as e:
            logger.error(f"Failed to update user last access: {e}")
            return False
    
    def get_user_resource_quota(self, user_id: int) -> Dict[str, str]:
        """
        Get user's resource quota from database
        
        Args:
            user_id: User ID
        
        Returns:
            Resource quota dict
        """
        try:
            with self.get_cursor() as cursor:
                # Check if there's a user_quota table or use default
                # For now, return default quota
                # You can extend this to query from a quota table
                
                return {
                    "cpu_request": settings.default_cpu_request,
                    "cpu_limit": settings.default_cpu_limit,
                    "memory_request": settings.default_memory_request,
                    "memory_limit": settings.default_memory_limit,
                    "storage": settings.default_storage_size
                }
                
        except pymysql.Error as e:
            logger.error(f"Failed to get user quota: {e}")
            return {
                "cpu_request": "500m",
                "cpu_limit": "2",
                "memory_request": "1Gi",
                "memory_limit": "4Gi",
                "storage": "10Gi"
            }
    
    def log_pod_creation(self, user_id: int, pod_name: str, access_info: Dict[str, Any]) -> bool:
        """
        Log pod creation event
        
        Args:
            user_id: User ID
            pod_name: Created pod name
            access_info: Access information
        
        Returns:
            True if logged successfully
        """
        try:
            with self.get_cursor() as cursor:
                # You can create a pod_logs table to track pod creation
                # For now, just log
                logger.info(f"Pod {pod_name} created for user {user_id}")
                return True
                
        except pymysql.Error as e:
            logger.error(f"Failed to log pod creation: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        Test database connection
        
        Returns:
            True if connection successful
        """
        try:
            with self.get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    return result is not None
        except pymysql.Error as e:
            logger.error(f"Database connection test failed: {e}")
            return False

# Singleton instance
db_manager = None

def get_db_manager() -> DatabaseManager:
    """Get or create database manager instance"""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager()
    return db_manager