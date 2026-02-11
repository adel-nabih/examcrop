"""
FastAPI Backend for Worksheet Splitter
YOLOv11 Custom Model for Question Detection
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import shutil
import zipfile
import os
from pathlib import Path
import io
import traceback
import fitz

from datetime import datetime
import uuid

from pocketbase import PocketBase
from contextlib import asynccontextmanager

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

from split_pdf import YOLOQuestionSplitter
from dotenv import load_dotenv
load_dotenv()

# ============================================================================
# 🔥 LOCAL TESTING ONLY - DELETE THIS ENTIRE BLOCK BEFORE DEPLOYMENT 🔥
# ============================================================================
# For OAuth, use these variables instead of service account JSON
"""
os.environ["GOOGLE_CLIENT_ID"] = "your-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "GOCSPX-your-secret"
os.environ["GOOGLE_REFRESH_TOKEN"] = "1//your-refresh-token"

os.environ["POCKETBASE_EMAIL"] = "your-email@example.com"
os.environ["POCKETBASE_PASSWORD"] = "your-password"
os.environ["SAVE_TO_DRIVE"] = "true"
"""
# ============================================================================
# 🔥 END LOCAL TESTING BLOCK - DELETE BEFORE DEPLOYMENT 🔥
# ============================================================================

# 1. Detect environment
IS_RAILWAY = os.environ.get("RAILWAY_ENVIRONMENT_NAME") is not None

# 2. Set URL based on environment
if IS_RAILWAY:
    # Production: Fast internal link
    POCKETBASE_URL = "http://pocketbase.railway.internal:8080"
else:
    # Local: Public link for your MacBook
    POCKETBASE_URL = "https://pocketbase-production-4854.up.railway.app"

# 3. Get Credentials from Environment
POCKETBASE_EMAIL = os.environ.get("POCKETBASE_EMAIL")
POCKETBASE_PASSWORD = os.environ.get("POCKETBASE_PASSWORD")

pb = PocketBase(POCKETBASE_URL)

# Google Drive Configuration
SAVE_TO_DRIVE = os.environ.get("SAVE_TO_DRIVE", "true").lower() == "true"
DRIVE_FOLDER_ID = "1LZgS5aNOwmEEYAbqIh3Vl285nTb8lt02"

# Initialize on startup
drive_service = None
yolo_splitter = None  # Cache the YOLO model globally


def get_drive_service():
    """Initialize Google Drive API client using OAuth"""
    try:
        # Get OAuth credentials from environment
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
        
        if not all([client_id, client_secret, refresh_token]):
            missing = []
            if not client_id: missing.append("GOOGLE_CLIENT_ID")
            if not client_secret: missing.append("GOOGLE_CLIENT_SECRET")
            if not refresh_token: missing.append("GOOGLE_REFRESH_TOKEN")
            print(f"⚠️ Missing OAuth credentials: {', '.join(missing)}")
            print("   Run get_oauth_token.py locally to get these values")
            return None
        
        # Create credentials from refresh token
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        # Refresh to get access token
        credentials.refresh(Request())
        
        service = build('drive', 'v3', credentials=credentials)
        print("✅ Google Drive OAuth initialized successfully")
        return service
    except Exception as e:
        print(f"❌ Failed to initialize Drive with OAuth: {e}")
        return None


def upload_to_drive(local_path, drive_filename, parent_folder_id):
    """Upload a file to Google Drive"""
    try:
        if not os.path.exists(local_path):
            print(f"⚠️ File not found for upload: {local_path}")
            return None, None
            
        file_metadata = {
            'name': drive_filename,
            'parents': [parent_folder_id]
        }
        
        media = MediaFileUpload(local_path, resumable=True)
        
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()
        
        print(f"✅ Uploaded: {drive_filename} (ID: {file.get('id')})")
        return file.get('id'), file.get('webViewLink')
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Drive upload failed for {drive_filename}: {e}")
        return None, None


def create_drive_folder(folder_name, parent_folder_id):
    """Create a folder in Google Drive"""
    try:
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        
        folder = drive_service.files().create(
            body=file_metadata,
            fields='id, webViewLink'
        ).execute()
        
        print(f"✅ Created folder: {folder_name} (ID: {folder.get('id')})")
        return folder.get('id')
    except Exception as e:
        print(f"❌ Drive folder creation failed: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global drive_service, yolo_splitter
    
    # Load YOLO model once at startup
    if os.path.exists("best.onnx"):
        print("🔥 Loading YOLO model at startup...")
        try:
            yolo_splitter = YOLOQuestionSplitter(debug=False, model_path="best.onnx", task="detect")
            print("✅ YOLO model loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load YOLO model: {e}")
            yolo_splitter = None
    else:
        print("⚠️ best.onnx model file not found")
        yolo_splitter = None
    
    # PocketBase Auth
    try:
        pb.admins.auth_with_password(POCKETBASE_EMAIL, POCKETBASE_PASSWORD)
        print("✅ Successfully authenticated with PocketBase")
    except Exception as e:
        print(f"❌ PocketBase Auth Failed: {e}")

    # Google Drive Init
    if SAVE_TO_DRIVE:
        drive_service = get_drive_service()
        if drive_service:
            print(f"✅ Google Drive enabled: folder {DRIVE_FOLDER_ID}")
        else:
            print("⚠️ Google Drive initialization failed")
    
    yield  # App runs
    
    print("Shutting down...")


app = FastAPI(
    title="Worksheet Splitter - YOLOv11 Custom",
    description="AI-powered question splitting using custom-trained YOLOv11",
    version="11.0.0",
    lifespan=lifespan
)

# CORS for frontend
origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost",
    "http://127.0.0.1",
    "https://examcrop.com",
    "https://www.examcrop.com",
    "https://pdf-splitter-production-9d84.up.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Questions-Count", "Content-Disposition"],
)


@app.get("/api")
def read_root():
    model_status = "trained" if os.path.exists("best.onnx") else "not_trained"
    
    return {
        "status": "ok",
        "service": "yolov11-question-splitter",
        "version": "11.0.0",
        "model": "YOLOv11 Custom Trained",
        "model_status": model_status,
    }


@app.post("/split")
@app.post("/api/split")
async def split_worksheet(
    file: UploadFile = File(...),
    dpi: int = 300,
    debug: bool = False,
    conf_threshold: float = 0.15
):
    """
    Split worksheets using custom-trained YOLOv11 model.
    
    Args:
        file: PDF, JPG, JPEG, or PNG
        dpi: Processing resolution (300-600 recommended)
        debug: Save intermediate visualization images
        conf_threshold: YOLO confidence threshold (0.05-0.95)
    
    Returns:
        ZIP file with individual question PDFs
    """
    
    # Check if model exists
    if not os.path.exists("best.onnx"):
        raise HTTPException(
            status_code=503,
            detail="Service Unavailable"
        )
    
    MAX_SIZE = 20 * 1024 * 1024
    MAX_PAGES = 20  # Free tier limit
    
    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)
    
    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size_mb:.1f}MB). Maximum file size is 20MB during our testing phase. For larger files, please wait for our Pro plan launch!"
        )
    
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    if not (100 <= dpi <= 600):
        raise HTTPException(
            status_code=400,
            detail="DPI must be between 100 and 600"
        )
    
    if not (0.05 <= conf_threshold <= 0.95):
        raise HTTPException(
            status_code=400,
            detail="Confidence threshold must be between 0.05 and 0.95"
        )
    
    # Generate unique ID for this upload
    upload_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Save uploaded file
        input_path = os.path.join(temp_dir, file.filename)
        with open(input_path, 'wb') as f:
            f.write(contents)
        
        print(f"\n{'='*70}")
        print(f"📁 Saved input file: {input_path}")
        print(f"   File exists: {os.path.exists(input_path)}")
        print(f"   File size: {os.path.getsize(input_path) / 1024:.1f} KB")
        
        # Check page count for PDFs BEFORE processing
        if file_ext == '.pdf':
            try:
                doc = fitz.open(input_path)
                page_count = len(doc)
                doc.close()
                
                if page_count > MAX_PAGES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Your PDF has {page_count} pages. During our testing phase, we support up to {MAX_PAGES} pages per document. We're working hard to bring you unlimited pages with our Pro plan soon! For now, please split your document into smaller sections. Thank you for your understanding! 🙏"
                    )
                
                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, {page_count} pages)")
            except HTTPException:
                raise
            except Exception as e:
                print(f"Warning: Could not check page count: {e}")
                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB)")
        else:
            # For images, assume 1 page
            print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, 1 page)")
        
        print(f"  DPI: {dpi}, Confidence: {conf_threshold}")
        
        # Create output directory
        output_dir = os.path.join(temp_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        # Use cached YOLO model (loaded at startup)
        if yolo_splitter is None:
            raise HTTPException(
                status_code=503,
                detail="Model not loaded. Please try again in a moment."
            )
        
        splitter = yolo_splitter
        
        try:
            import time
            start_time = time.time()
            
            splitter.split_worksheet(
                input_path=input_path,
                output_dir=output_dir,
                dpi=dpi,
                cleanup_temp=True,
                conf_threshold=conf_threshold
            )
            
            processing_time = time.time() - start_time
            print(f"⏱️ Processing completed in {processing_time:.2f} seconds")
        except SystemExit:
            raise HTTPException(
                status_code=422,
                detail="No questions detected"
            )
        
        # Check output
        output_files = list(Path(output_dir).glob('*.pdf'))
        
        if not output_files:
            raise HTTPException(
                status_code=422,
                detail="No questions detected"
            )
        
        print(f"✓ Successfully split into {len(output_files)} questions")
        print(f"📂 Output files:")
        for pdf in sorted(output_files):
            print(f"   - {pdf.name} ({pdf.stat().st_size / 1024:.1f} KB)")
        
        # Create combined PDF with all questions
        combined_pdf = fitz.open()
        for pdf_file in sorted(output_files):
            src_pdf = fitz.open(pdf_file)
            combined_pdf.insert_pdf(src_pdf)
            src_pdf.close()
        combined_path = os.path.join(output_dir, 'all_questions_combined.pdf')
        combined_pdf.save(combined_path, garbage=4, deflate=True, clean=True, pretty=False,)
        combined_pdf.close()
        
        print(f"✓ Created combined PDF: {combined_path}")
        print(f"   File exists: {os.path.exists(combined_path)}")
        print(f"   File size: {os.path.getsize(combined_path) / 1024:.1f} KB")
        
        # 🆕 UPLOAD TO GOOGLE DRIVE - AFTER ALL FILES ARE CREATED
        if SAVE_TO_DRIVE and drive_service:
            print(f"\n{'='*70}")
            print("📤 Starting Google Drive upload...")
            print(f"{'='*70}")
            
            try:
                # Create a folder for this upload
                upload_folder_name = f"{upload_id}_{Path(file.filename).stem}"
                upload_folder_id = create_drive_folder(upload_folder_name, DRIVE_FOLDER_ID)
                
                if upload_folder_id:
                    # Upload original file
                    print(f"\n1️⃣ Uploading original file...")
                    upload_to_drive(input_path, f"original_{file.filename}", upload_folder_id)
                    
                    # Create and upload metadata
                    print(f"\n2️⃣ Creating metadata...")
                    metadata = {
                        "upload_id": upload_id,
                        "timestamp": datetime.now().isoformat(),
                        "filename": file.filename,
                        "file_size_mb": round(file_size_mb, 2),
                        "dpi": dpi,
                        "conf_threshold": conf_threshold,
                        "questions_detected": len(output_files),
                        "processing_status": "success"
                    }
                    
                    metadata_path = os.path.join(temp_dir, 'metadata.json')
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    
                    upload_to_drive(metadata_path, 'metadata.json', upload_folder_id)
                    
                    # Create output subfolder
                    print(f"\n3️⃣ Creating output subfolder...")
                    output_folder_id = create_drive_folder('output', upload_folder_id)
                    
                    if output_folder_id:
                        # Upload combined PDF first
                        print(f"\n4️⃣ Uploading combined PDF...")
                        upload_to_drive(combined_path, 'all_questions_combined.pdf', output_folder_id)
                        
                        # Upload all individual question PDFs
                        print(f"\n5️⃣ Uploading {len(output_files)} individual question PDFs...")
                        for i, pdf_file in enumerate(sorted(output_files), 1):
                            print(f"   [{i}/{len(output_files)}] Uploading {pdf_file.name}...")
                            upload_to_drive(str(pdf_file), pdf_file.name, output_folder_id)
                        
                        # Upload debug images if they exist
                        debug_files = list(Path(temp_dir).glob('debug_*.png'))
                        if debug_files:
                            print(f"\n6️⃣ Uploading {len(debug_files)} debug images...")
                            debug_folder_id = create_drive_folder('debug', upload_folder_id)
                            if debug_folder_id:
                                for debug_file in debug_files:
                                    upload_to_drive(str(debug_file), debug_file.name, debug_folder_id)
                    
                    print(f"\n{'='*70}")
                    print(f"✅ Successfully uploaded to Google Drive: {upload_folder_name}")
                    print(f"{'='*70}\n")
                
            except Exception as e:
                print(f"\n{'='*70}")
                print(f"⚠️ Failed to upload to Drive: {e}")
                print(f"{'='*70}\n")
                traceback.print_exc()
                # Don't fail the request if Drive upload fails
        
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add combined PDF
            zip_file.write(combined_path, 'all_questions_combined.pdf')
            
            # Add question PDFs
            for pdf_file in sorted(output_files):
                zip_file.write(pdf_file, pdf_file.name)
            
            # Add debug images if enabled
            if debug:
                for debug_file in Path(temp_dir).glob('debug_*.png'):
                    zip_file.write(debug_file, f"debug/{debug_file.name}")
        
        zip_buffer.seek(0)
        
        base_name = Path(file.filename).stem
        zip_filename = f"{base_name}_questions.zip"
        
        print(f"✓ Created ZIP: {zip_filename} ({len(zip_buffer.getvalue()) / 1024 / 1024:.2f}MB)")
        
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename={zip_filename}",
                "X-Questions-Count": str(len(output_files)),
                "X-Method": "YOLOv11-Custom",
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"\n❌ ERROR: {error_trace}")
        
        # 🆕 LOG ERRORS TO DRIVE
        if SAVE_TO_DRIVE and drive_service:
            try:
                print(f"\n{'='*70}")
                print("📤 Logging error to Google Drive...")
                print(f"{'='*70}")
                
                upload_folder_name = f"{upload_id}_ERROR_{Path(file.filename).stem}"
                upload_folder_id = create_drive_folder(upload_folder_name, DRIVE_FOLDER_ID)
                
                if upload_folder_id:
                    # Upload error log
                    error_path = os.path.join(temp_dir, 'error.log')
                    with open(error_path, 'w') as f:
                        f.write(error_trace)
                    upload_to_drive(error_path, 'error.log', upload_folder_id)
                    
                    # Upload original file if it exists
                    if os.path.exists(input_path):
                        upload_to_drive(input_path, f"original_{file.filename}", upload_folder_id)
                    
                    # Upload metadata with error
                    metadata = {
                        "upload_id": upload_id,
                        "timestamp": datetime.now().isoformat(),
                        "filename": file.filename,
                        "file_size_mb": round(file_size_mb, 2),
                        "dpi": dpi,
                        "conf_threshold": conf_threshold,
                        "processing_status": "error",
                        "error": str(e)
                    }
                    
                    metadata_path = os.path.join(temp_dir, 'metadata.json')
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)
                    upload_to_drive(metadata_path, 'metadata.json', upload_folder_id)
                    
                    print(f"✅ Error logged to Drive: {upload_folder_name}\n")
                    
            except Exception as log_err:
                print(f"⚠️ Failed to log error to Drive: {log_err}")
                traceback.print_exc()
        
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )
    
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"Cleanup warning: {e}")


@app.get("/api/health")
def health_check():
    model_exists = os.path.exists("best.onnx")
    
    return {
        "status": "healthy" if model_exists else "model_missing",
        "method": "YOLOv11 Custom Trained",
        "model_ready": model_exists,
        "drive_enabled": SAVE_TO_DRIVE,
        "drive_ready": drive_service is not None
    }


@app.get("/api/info")
def get_info():
    return {
        "service": "YOLOv11 Question Splitter",
        "version": "11.0.0",
        "description": "Custom-trained YOLOv11 for worksheet question detection",
        "supported_formats": ["PDF", "JPG", "JPEG", "PNG"],
        "max_file_size": "20MB",
        "max_pages": "20 pages (testing phase)",
        "recommended_dpi": 300
    }


@app.get("/sample")
@app.get("/api/sample")
async def get_sample_file():
    """Serve the sample worksheet file"""
    # Debug: Show what files we can see
    print("\n" + "="*70)
    print("🔍 Looking for sample file...")
    print(f"Current working directory: {os.getcwd()}")
    print(f"Files in current dir: {os.listdir('.')}")
    
    if os.path.exists('frontend'):
        print(f"Files in frontend/: {os.listdir('frontend')}")
    else:
        print("❌ frontend/ directory not found")
    
    # Check multiple possible locations
    possible_paths = [
        Path("frontend/sample.png"),
        Path("../frontend/sample.png"),
        Path("./sample.png"),
        Path("sample.png"),
        Path("frontend/sample_worksheet.pdf"),
        Path("../frontend/sample_worksheet.pdf"),
        Path("./sample_worksheet.pdf"),
    ]
    
    for sample_path in possible_paths:
        print(f"Checking: {sample_path} -> Exists: {sample_path.exists()}")
        if sample_path.exists():
            print(f"✅ Serving sample from: {sample_path}")
            print("="*70 + "\n")
            return FileResponse(sample_path)
    
    print("❌ Sample file not found in any location")
    print("="*70 + "\n")
    raise HTTPException(
        status_code=404,
        detail="Sample file not found. Please upload your own file."
    )


@app.post("/api/feedback")
async def collect_feedback(request: dict):
    """Collect user feedback and save to PocketBase"""
    try:
        email = request.get('email', '')
        comment = request.get('comment', '')
        timestamp = request.get('timestamp', '')
        
        # Validate
        if not email and not comment:
            return {"status": "success", "message": "No data provided"}
        
        # Save to PocketBase
        data = {
            "email": email or "",
            "feedback": comment or "",
            "timestamp": timestamp or ""
        }
        
        record = pb.collection('leads').create(data)
        
        print(f"✓ Saved lead: {email}")
        
        return {
            "status": "success",
            "message": "Thank you for your feedback!",
            "id": record.id
        }
        
    except Exception as e:
        print(f"❌ PocketBase save error: {e}")
        # Don't fail - just log the error
        return {"status": "error", "message": str(e)}


@app.get("/")
@app.get("/{path_name:path}")
async def serve_frontend(path_name: str = None):
    # 1. Define where the frontend files might live
    # Docker usually puts them in /app/frontend, but local is ../frontend
    possible_folders = [Path("frontend"), Path("../frontend"), Path(".")]
    
    # 2. If the browser is asking for a specific file (like script.js or styles.css)
    if path_name and "." in path_name:
        for folder in possible_folders:
            file_path = folder / path_name
            if file_path.exists():
                return FileResponse(file_path)

    # 3. Otherwise, serve the main index.html
    for folder in possible_folders:
        index_path = folder / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

    # 4. If we get here, the files are missing
    raise HTTPException(
        status_code=404, 
        detail="Frontend files not found. Check your Docker COPY commands."
    )

if __name__ == "__main__":
    import uvicorn
    import os
    
    # This allows Railway to tell your app which port to use
    port = int(os.environ.get("PORT", 8000))
    
    print("="*70)
    print(f"Running on port: {port}")
    print("="*70)
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")