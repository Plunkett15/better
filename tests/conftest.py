# --- START OF FILE tests/conftest.py ---

import pytest
import os
import tempfile
import shutil

# Import the Flask app factory or instance
# Using a factory pattern (create_app) is generally better,
# but for simplicity here, we'll import the created app instance.
# Ensure your app.py structure allows this or adapt as needed.
from app import app as flask_app
from database import init_db, get_db_connection, DATABASE_PATH

@pytest.fixture(scope='session')
def app():
    """Session-wide test Flask application."""

    # Use a temporary directory for instance folder during tests
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    temp_instance_path = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_instance_path, 'test_videos.db')

    # --- Configure App for Testing ---
    flask_app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False, # Disable CSRF for easier testing of forms/POST requests
        "DATABASE_PATH": test_db_path, # Use a temporary test database
        "INSTANCE_FOLDER_PATH": temp_instance_path,
        # Add other test-specific configs, e.g., disable external APIs
        "GEMINI_API_KEY": None, # Disable external API calls during tests unless specifically mocked
    })

    print(f"Using test database: {test_db_path}")
    print(f"Using test instance folder: {temp_instance_path}")

    # --- Initialize Test Database ---
    try:
        with flask_app.app_context():
            # Ensure the database module uses the overridden path
            # This might require modifying database.py to check app.config if not already doing so,
            # or directly passing the path to init_db if possible.
            # For now, assume init_db uses the DATABASE_PATH set above.
            init_db()
        print("Test database initialized.")
    except Exception as e:
        print(f"Error initializing test database: {e}")
        # Clean up before failing
        os.close(db_fd)
        os.unlink(db_path) # Remove the temp file used by mkstemp if different
        shutil.rmtree(temp_instance_path)
        pytest.fail(f"Test database initialization failed: {e}")


    yield flask_app # Provide the configured app instance to tests

    # --- Cleanup ---
    print("Cleaning up test database and instance folder...")
    os.close(db_fd)
    # os.unlink(db_path) # mkstemp file might not be the one used if path was overridden
    shutil.rmtree(temp_instance_path) # Remove the temporary instance folder and its contents
    print("Test cleanup complete.")


@pytest.fixture()
def client(app):
    """A test client for the Flask application."""
    return app.test_client()


@pytest.fixture()
def runner(app):
    """A test CLI runner for the Flask application (if you have CLI commands)."""
    return app.test_cli_runner()

@pytest.fixture()
def db_conn(app):
    """Provides a direct connection to the test database."""
    # Ensure get_db_connection uses the test path from app.config
    # This might require modifying get_db_connection to accept a path or read from config
    # Assuming it reads the config path set in the 'app' fixture for now.
    try:
        # Need to use the context manager correctly
        with get_db_connection() as conn:
            yield conn
        # Connection is closed automatically by the context manager
    except Exception as e:
        pytest.fail(f"Failed to get test DB connection: {e}")


# --- END OF FILE tests/conftest.py ---