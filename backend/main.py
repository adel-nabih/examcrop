"""
FastAPI Backend for Worksheet Splitter
YOLOv11 Custom Model for Question Detection
OPTIMIZED: Background Google Drive uploads
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
import threading

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
        
        return file.get('id'), file.get('webViewLink')
    except Exception as e:
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
        
        return folder.get('id')
    except Exception as e:
        print(f"❌ Drive folder creation failed: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global drive_service, yolo_splitter
    
    # Load YOLO model once at startup
    if os.path.exists("best.pt"):
        print("🔥 Loading YOLO model at startup...")
        try:
            yolo_splitter = YOLOQuestionSplitter(debug=False, model_path="best.pt")
            print("✅ YOLO model loaded successfully")
        except Exception as e:
            print(f"❌ Failed to load YOLO model: {e}")
            yolo_splitter = None
    else:
        print("⚠️ best.pt model file not found")
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
    model_status = "trained" if os.path.exists("best.pt") else "not_trained"
    
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
    dpi: int = 150,  # Reduced default from 300 for speed
    debug: bool = False,
    conf_threshold: float = 0.10  # Optimized default
):
    """
    Split worksheets using custom-trained YOLOv11 model.
    
    Args:
        file: PDF, JPG, JPEG, or PNG
        dpi: Processing resolution (150-300 recommended, lower = faster)
        debug: Save intermediate visualization images
        conf_threshold: YOLO confidence threshold (0.05-0.30, lower = more detections)
    
    Returns:
        ZIP file with individual question PDFs
    """
    
    # Check if model exists
    if yolo_splitter is None:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please try again in a moment."
        )
    
    MAX_SIZE = 20 * 1024 * 1024
    MAX_PAGES = 20  # Free tier limit
    
    contents = await file.read()
    file_size_mb = len(contents) / (1024 * 1024)
    
    if len(contents) > MAX_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size_mb:.1f}MB). Maximum file size is 20MB."
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
        import time
        start_time = time.time()
        
        # Save uploaded file
        input_path = os.path.join(temp_dir, file.filename)
        with open(input_path, 'wb') as f:
            f.write(contents)
        
        # Check page count for PDFs BEFORE processing
        if file_ext == '.pdf':
            try:
                doc = fitz.open(input_path)
                page_count = len(doc)
                doc.close()
                
                if page_count > MAX_PAGES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Your PDF has {page_count} pages. Maximum {MAX_PAGES} pages supported."
                    )
                
                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, {page_count} pages)")
            except HTTPException:
                raise
            except Exception as e:
                print(f"Warning: Could not check page count: {e}")
                print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB)")
        else:
            print(f"\nProcessing: {file.filename} ({file_size_mb:.1f}MB, 1 page)")
        
        # Create output directory
        output_dir = os.path.join(temp_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        # Use cached YOLO model
        splitter = yolo_splitter
        
        try:
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
        
        # Create combined PDF with all questions
        combined_pdf = fitz.open()
        for pdf_file in sorted(output_files):
            src_pdf = fitz.open(pdf_file)
            combined_pdf.insert_pdf(src_pdf)
            src_pdf.close()
        combined_path = os.path.join(output_dir, 'all_questions_combined.pdf')
        combined_pdf.save(combined_path, garbage=4, deflate=True, clean=True, pretty=False)
        combined_pdf.close()
        
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
        
        total_time = time.time() - start_time
        print(f"✓ Total time: {total_time:.2f}s | ZIP: {zip_filename} ({len(zip_buffer.getvalue()) / 1024 / 1024:.2f}MB)")
        
        # 🚀 BACKGROUND UPLOAD TO GOOGLE DRIVE (DON'T BLOCK RESPONSE)
        if SAVE_TO_DRIVE and drive_service:
            # Prepare data for background upload
            background_data = {
                'input_path': input_path,
                'output_files': [str(f) for f in sorted(output_files)],
                'combined_path': combined_path,
                'temp_dir': temp_dir,
                'upload_id': upload_id,
                'filename': file.filename,
                'file_size_mb': file_size_mb,
                'dpi': dpi,
                'conf_threshold': conf_threshold,
                'questions_count': len(output_files)
            }
            
            def upload_async():
                """Background thread for Google Drive upload"""
                try:
                    print(f"\n🚀 Background upload started: {background_data['upload_id']}")
                    
                    upload_folder_name = f"{background_data['upload_id']}_{Path(background_data['filename']).stem}"
                    upload_folder_id = create_drive_folder(upload_folder_name, DRIVE_FOLDER_ID)
                    
                    if upload_folder_id:
                        # Upload original
                        upload_to_drive(background_data['input_path'], 
                                      f"original_{background_data['filename']}", 
                                      upload_folder_id)
                        
                        # Create and upload metadata
                        metadata = {
                            "upload_id": background_data['upload_id'],
                            "timestamp": datetime.now().isoformat(),
                            "filename": background_data['filename'],
                            "file_size_mb": background_data['file_size_mb'],
                            "dpi": background_data['dpi'],
                            "conf_threshold": background_data['conf_threshold'],
                            "questions_detected": background_data['questions_count'],
                            "processing_status": "success"
                        }
                        
                        metadata_path = os.path.join(background_data['temp_dir'], 'metadata.json')
                        with open(metadata_path, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        upload_to_drive(metadata_path, 'metadata.json', upload_folder_id)
                        
                        # Create output subfolder
                        output_folder_id = create_drive_folder('output', upload_folder_id)
                        if output_folder_id:
                            # Upload combined PDF
                            upload_to_drive(background_data['combined_path'], 
                                          'all_questions_combined.pdf', 
                                          output_folder_id)
                            
                            # Upload individual questions
                            for pdf_path in background_data['output_files']:
                                upload_to_drive(pdf_path, Path(pdf_path).name, output_folder_id)
                        
                        print(f"✅ Background upload completed: {upload_folder_name}")
                
                except Exception as e:
                    print(f"⚠️ Background upload failed: {e}")
                    traceback.print_exc()
                
                finally:
                    # Clean up temp files after upload
                    try:
                        if os.path.exists(background_data['temp_dir']):
                            shutil.rmtree(background_data['temp_dir'])
                            print(f"🗑️ Cleaned up temp directory: {background_data['upload_id']}")
                    except Exception as e:
                        print(f"⚠️ Cleanup warning: {e}")
            
            # Start background upload thread (daemon=True means it won't block shutdown)
            upload_thread = threading.Thread(target=upload_async, daemon=True)
            upload_thread.start()
            print("🚀 Started background upload (not blocking response)")
        else:
            # No Drive upload - clean up immediately
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    print(f"Cleanup warning: {e}")
        
        # Return response immediately (don't wait for upload!)
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
        # Clean up on error
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
        raise
    
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"\n❌ ERROR: {error_trace}")
        
        # 🆕 LOG ERRORS TO DRIVE (also in background)
        if SAVE_TO_DRIVE and drive_service:
            error_data = {
                'temp_dir': temp_dir,
                'input_path': input_path if 'input_path' in locals() else None,
                'upload_id': upload_id,
                'filename': file.filename,
                'file_size_mb': file_size_mb,
                'dpi': dpi,
                'conf_threshold': conf_threshold,
                'error': str(e),
                'error_trace': error_trace
            }
            
            def log_error_async():
                try:
                    upload_folder_name = f"{error_data['upload_id']}_ERROR_{Path(error_data['filename']).stem}"
                    upload_folder_id = create_drive_folder(upload_folder_name, DRIVE_FOLDER_ID)
                    
                    if upload_folder_id:
                        # Upload error log
                        error_path = os.path.join(error_data['temp_dir'], 'error.log')
                        with open(error_path, 'w') as f:
                            f.write(error_data['error_trace'])
                        upload_to_drive(error_path, 'error.log', upload_folder_id)
                        
                        # Upload original file if exists
                        if error_data['input_path'] and os.path.exists(error_data['input_path']):
                            upload_to_drive(error_data['input_path'], 
                                          f"original_{error_data['filename']}", 
                                          upload_folder_id)
                        
                        # Upload metadata
                        metadata = {
                            "upload_id": error_data['upload_id'],
                            "timestamp": datetime.now().isoformat(),
                            "filename": error_data['filename'],
                            "file_size_mb": error_data['file_size_mb'],
                            "dpi": error_data['dpi'],
                            "conf_threshold": error_data['conf_threshold'],
                            "processing_status": "error",
                            "error": error_data['error']
                        }
                        
                        metadata_path = os.path.join(error_data['temp_dir'], 'metadata.json')
                        with open(metadata_path, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        upload_to_drive(metadata_path, 'metadata.json', upload_folder_id)
                        
                        print(f"✅ Error logged to Drive: {upload_folder_name}")
                except Exception as log_err:
                    print(f"⚠️ Failed to log error: {log_err}")
                finally:
                    # Clean up
                    if error_data['temp_dir'] and os.path.exists(error_data['temp_dir']):
                        try:
                            shutil.rmtree(error_data['temp_dir'])
                        except:
                            pass
            
            error_thread = threading.Thread(target=log_error_async, daemon=True)
            error_thread.start()
        else:
            # No Drive - clean up immediately
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
        
        raise HTTPException(
            status_code=500,
            detail=f"Processing failed: {str(e)}"
        )


@app.get("/api/health")
def health_check():
    model_exists = os.path.exists("best.pt")
    
    return {
        "status": "healthy" if model_exists else "model_missing",
        "method": "YOLOv11 Custom Trained",
        "model_ready": yolo_splitter is not None,
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
        "recommended_dpi": 150,
        "recommended_conf": 0.10
    }

@app.get("/sample")
@app.get("/api/sample")
async def get_sample_file():
    """Serve the sample worksheet file"""
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
        if sample_path.exists():
            return FileResponse(sample_path)
    
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
        return {"status": "error", "message": str(e)}


@app.get("/")
@app.get("/{path_name:path}")
async def serve_frontend(path_name: str = None):
    possible_folders = [Path("frontend"), Path("../frontend"), Path(".")]
    
    if path_name and "." in path_name:
        for folder in possible_folders:
            file_path = folder / path_name
            if file_path.exists():
                return FileResponse(file_path)

    for folder in possible_folders:
        index_path = folder / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

    raise HTTPException(
        status_code=404, 
        detail="Frontend files not found."
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    
    print("="*70)
    print(f"Running on port: {port}")
    print("="*70)
    
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")