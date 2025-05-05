# --- Start of File: celery_app.py ---
from celery import Celery
from config import Config # Import your configuration class

# Instantiate the configuration
config = Config()

# Create the Celery application instance
celery_app = Celery(
    'video_processor_tasks', # Can be any name, helps identify workers/logs
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    # <<< MODIFIED: Point include to the single tasks.py file >>>
    include=['tasks']
)

# --- Load Celery configuration from the Config object ---
# Option 1: If keys in config.py are CELERY_BROKER_URL, CELERY_RESULT_BACKEND etc.
celery_app.config_from_object(config)

# Option 2: If keys in config.py are prefixed like CELERY_BROKER_URL etc.
# celery_app.config_from_object(config, namespace='CELERY')

# --- Optional: Task Configuration ---
celery_app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='UTC', # Explicitly set timezone
    enable_utc=True,
    # Track when tasks are started by workers
    task_track_started=True,
    # Optional: Set worker prefetch multiplier (can affect memory usage vs throughput)
    # worker_prefetch_multiplier=1, # Process one message at a time (good for long tasks / high memory)
    # Optional: Task result expiration time (e.g., results expire after 1 day)
    # result_expires=86400, # In seconds
    # Optional: Broker connection pool limits (if needed for high volume)
    # broker_pool_limit=10,
)

# Optional: If you have complex routing or queues, define them here
# from kombu import Queue
# celery_app.conf.task_queues = (
#     Queue('default', routing_key='task.#'),
#     Queue('gpu_tasks', routing_key='gpu.#'), # Example GPU queue
# )
# celery_app.conf.task_default_queue = 'default'
# celery_app.conf.task_default_exchange = 'tasks'
# celery_app.conf.task_default_routing_key = 'task.default'

# --- Autodiscovery (usually not strictly needed if `include` is used) ---
# celery_app.autodiscover_tasks() # Uncomment if tasks are spread across multiple modules auto-discovered

if __name__ == '__main__':
    # This allows running the worker directly using `python celery_app.py worker`
    # although `celery -A celery_app.celery_app worker --loglevel=INFO` is the standard command.
    print("Starting Celery worker from celery_app.py...")
    celery_app.worker_main(argv=['worker', '--loglevel=INFO'])

# --- END OF FILE celery_app.py ---