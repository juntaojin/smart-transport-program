from fastapi.middleware.cors import CORSMiddleware

def setup_middleware(app):
    """
    Configure CORS middleware for FastAPI application to allow frontend access
    from alternative development ports (e.g. 5173).
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify front-end domains
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
