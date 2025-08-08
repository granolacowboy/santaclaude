"""
Event Dispatcher - Redis Streams Implementation
Handles event routing, delivery, and consumer management
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
import logging

import redis.asyncio as redis
from redis.exceptions import ResponseError, ConnectionError as RedisConnectionError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class Event:
    """Represents a message queue event"""
    event_type: str
    payload: Dict[str, Any]
    correlation_id: Optional[str] = None
    user_id: Optional[int] = None
    request_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    retry_count: int = 0
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.correlation_id is None:
            self.correlation_id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary"""
        if 'timestamp' in data and isinstance(data['timestamp'], str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class ConsumerGroup:
    """Manages a consumer group for a stream"""
    
    def __init__(self, stream_name: str, group_name: str, redis_client: redis.Redis):
        self.stream_name = stream_name
        self.group_name = group_name
        self.redis = redis_client
        self.consumers: Dict[str, asyncio.Task] = {}
        self.message_handlers: Dict[str, Callable] = {}
        self._running = False
    
    async def initialize(self):
        """Initialize consumer group"""
        try:
            await self.redis.xgroup_create(
                self.stream_name, 
                self.group_name, 
                id='0', 
                mkstream=True
            )
            logger.info(f"Created consumer group {self.group_name} for stream {self.stream_name}")
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            # Group already exists
            logger.debug(f"Consumer group {self.group_name} already exists")
    
    def register_handler(self, event_type: str, handler: Callable[[Event], None]):
        """Register a message handler for specific event type"""
        self.message_handlers[event_type] = handler
        logger.info(f"Registered handler for event type: {event_type}")
    
    async def start_consumer(self, consumer_name: str):
        """Start a consumer in this group"""
        if consumer_name in self.consumers:
            return
        
        consumer_task = asyncio.create_task(
            self._consumer_loop(consumer_name)
        )
        self.consumers[consumer_name] = consumer_task
        logger.info(f"Started consumer {consumer_name} for group {self.group_name}")
    
    async def stop_consumers(self):
        """Stop all consumers in this group"""
        self._running = False
        
        for consumer_name, task in self.consumers.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.info(f"Stopped consumer {consumer_name}")
        
        self.consumers.clear()
    
    async def _consumer_loop(self, consumer_name: str):
        """Main consumer processing loop"""
        self._running = True
        
        while self._running:
            try:
                # Read messages from stream
                messages = await self.redis.xreadgroup(
                    self.group_name,
                    consumer_name,
                    {self.stream_name: '>'},
                    count=settings.BATCH_SIZE,
                    block=settings.CONSUMER_BLOCK_TIME
                )
                
                for stream, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        await self._process_message(consumer_name, message_id, fields)
                        
            except asyncio.CancelledError:
                break
            except RedisConnectionError:
                logger.error("Redis connection lost, retrying...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in consumer {consumer_name}: {e}")
                await asyncio.sleep(1)
    
    async def _process_message(self, consumer_name: str, message_id: bytes, fields: Dict):
        """Process a single message"""
        try:
            # Decode message fields
            decoded_fields = {k.decode(): v.decode() for k, v in fields.items()}
            
            # Parse event data
            event_data = json.loads(decoded_fields.get('data', '{}'))
            event = Event.from_dict(event_data)
            
            # Find appropriate handler
            handler = self.message_handlers.get(event.event_type)
            if handler:
                await handler(event)
            else:
                logger.warning(f"No handler found for event type: {event.event_type}")
            
            # Acknowledge message
            await self.redis.xack(self.stream_name, self.group_name, message_id)
            
            logger.debug(f"Processed message {message_id} by {consumer_name}")
            
        except Exception as e:
            logger.error(f"Failed to process message {message_id}: {e}")
            
            # Handle failure - could implement retry logic here
            if settings.DLQ_ENABLED:
                await self._send_to_dlq(message_id, fields, e)


    async def _send_to_dlq(self, message_id: bytes, fields: Dict, error: Exception):
        """Send failed message to dead letter queue"""
        dlq_stream = f"{self.stream_name}{settings.DLQ_STREAM_SUFFIX}"
        
        try:
            dlq_data = {
                'original_message_id': message_id.decode(),
                'original_stream': self.stream_name,
                'error': str(error),
                'timestamp': datetime.utcnow().isoformat(),
                'fields': {k.decode(): v.decode() for k, v in fields.items()}
            }
            
            await self.redis.xadd(
                dlq_stream,
                dlq_data,
                maxlen=settings.DEFAULT_MAX_LEN
            )
            
            logger.info(f"Sent message {message_id} to DLQ: {dlq_stream}")
            
        except Exception as dlq_error:
            logger.error(f"Failed to send message to DLQ: {dlq_error}")


class EventDispatcher:
    """Main event dispatcher using Redis Streams"""
    
    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.streams: Dict[str, str] = settings.EVENT_STREAMS
        self.consumer_groups: Dict[str, ConsumerGroup] = {}
        self.consumers: Dict[str, asyncio.Task] = {}
        self._running = False
    
    async def start(self):
        """Start the event dispatcher"""
        logger.info("Starting event dispatcher...")
        
        # Initialize Redis connection
        self.redis = redis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            retry_on_timeout=settings.REDIS_RETRY_ON_TIMEOUT,
            decode_responses=False
        )
        
        # Test connection
        await self.redis.ping()
        
        # Initialize consumer groups for each stream
        for stream_name in set(self.streams.values()):
            group_name = f"{stream_name}-consumers"
            consumer_group = ConsumerGroup(stream_name, group_name, self.redis)
            
            await consumer_group.initialize()
            self.consumer_groups[stream_name] = consumer_group
            
            # Start default consumers
            for i in range(settings.CONSUMER_COUNT):
                consumer_name = f"{group_name}-{i}"
                await consumer_group.start_consumer(consumer_name)
        
        self._running = True
        logger.info("Event dispatcher started")
    
    async def stop(self):
        """Stop the event dispatcher"""
        logger.info("Stopping event dispatcher...")
        
        self._running = False
        
        # Stop all consumer groups
        for consumer_group in self.consumer_groups.values():
            await consumer_group.stop_consumers()
        
        # Close Redis connection
        if self.redis:
            await self.redis.close()
        
        logger.info("Event dispatcher stopped")
    
    def is_ready(self) -> bool:
        """Check if dispatcher is ready"""
        return (
            self._running and 
            self.redis is not None and 
            len(self.consumer_groups) > 0
        )
    
    async def publish_event(self, event: Event) -> str:
        """Publish an event to appropriate stream"""
        if not self.redis:
            raise RuntimeError("Event dispatcher not started")
        
        # Determine target stream
        stream_name = self.streams.get(event.event_type)
        if not stream_name:
            logger.warning(f"No stream configured for event type: {event.event_type}")
            stream_name = "default-events"
        
        # Prepare event data
        event_data = {
            'data': json.dumps(event.to_dict()),
            'event_type': event.event_type,
            'timestamp': event.timestamp.isoformat(),
            'correlation_id': event.correlation_id
        }
        
        # Add to stream
        message_id = await self.redis.xadd(
            stream_name,
            event_data,
            maxlen=settings.DEFAULT_MAX_LEN
        )
        
        logger.debug(f"Published event {event.event_type} to {stream_name}: {message_id}")
        return message_id.decode()
    
    async def publish_events_batch(self, events: List[Event]) -> List[str]:
        """Publish multiple events in batch"""
        message_ids = []
        for event in events:
            message_id = await self.publish_event(event)
            message_ids.append(message_id)
        return message_ids
    
    def register_event_handler(self, event_type: str, handler: Callable[[Event], None]):
        """Register an event handler"""
        stream_name = self.streams.get(event_type)
        if stream_name and stream_name in self.consumer_groups:
            self.consumer_groups[stream_name].register_handler(event_type, handler)
        else:
            logger.warning(f"No consumer group found for event type: {event_type}")
    
    async def get_stream_info(self, stream_name: str) -> Dict[str, Any]:
        """Get information about a stream"""
        if not self.redis:
            return {}
        
        try:
            info = await self.redis.xinfo_stream(stream_name)
            return {
                'length': info.get(b'length', 0),
                'first_entry': info.get(b'first-entry'),
                'last_entry': info.get(b'last-entry'),
                'groups': info.get(b'groups', 0)
            }
        except ResponseError:
            return {}
    
    async def get_consumer_group_info(self, stream_name: str, group_name: str) -> Dict[str, Any]:
        """Get information about a consumer group"""
        if not self.redis:
            return {}
        
        try:
            groups = await self.redis.xinfo_groups(stream_name)
            for group in groups:
                if group[b'name'].decode() == group_name:
                    return {
                        'consumers': group.get(b'consumers', 0),
                        'pending': group.get(b'pending', 0),
                        'last_delivered_id': group.get(b'last-delivered-id', b'').decode()
                    }
        except ResponseError:
            pass
        
        return {}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get dispatcher statistics"""
        return {
            "running": self._running,
            "streams_count": len(self.streams),
            "consumer_groups_count": len(self.consumer_groups),
            "event_types": list(self.streams.keys()),
            "stream_mapping": self.streams
        }