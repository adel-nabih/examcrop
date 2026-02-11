// API Configuration
const API_BASE = (() => {
    const hostname = window.location.hostname;
    
    // Local development
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'http://localhost:8000';
    }
    
    // Production on examcrop.com
    if (hostname === 'examcrop.com' || hostname === 'www.examcrop.com') {
        return 'https://pdf-splitter-production-9d84.up.railway.app';
    }
    
    // Fallback to current origin
    return '';
})();

console.log('Using API:', API_BASE);

// DOM Elements
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const fileInfo = document.getElementById('fileInfo');
const fileName = document.getElementById('fileName');
const fileSize = document.getElementById('fileSize');
const splitBtn = document.getElementById('splitBtn');
const sampleBtn = document.getElementById('sampleBtn');
const progressContainer = document.getElementById('progressContainer');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const loading = document.getElementById('loading');
const errorMsg = document.getElementById('errorMsg');
const successMsg = document.getElementById('successMsg');

// Email Modal Elements
const modalOverlay = document.getElementById('modalOverlay');
const modalClose = document.getElementById('modalClose');
const emailForm = document.getElementById('emailForm');
const emailInput = document.getElementById('emailInput');
const commentInput = document.getElementById('commentInput');
const marketingOptIn = document.getElementById('marketingOptIn');

// Viewer Modal Elements
const viewerOverlay = document.getElementById('viewerOverlay');
const viewerClose = document.getElementById('viewerClose');
const viewerImage = document.getElementById('viewerImage');
const viewerTitle = document.getElementById('viewerTitle');
const viewerCounter = document.getElementById('viewerCounter');
const viewerPrev = document.getElementById('viewerPrev');
const viewerNext = document.getElementById('viewerNext');
const downloadCurrent = document.getElementById('downloadCurrent');
const downloadAll = document.getElementById('downloadAll');

// State
let selectedFile = null;
let pendingDownload = null;
let processedQuestions = [];
let currentQuestionIndex = 0;
let isDemo = false;

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});

// Upload Area Events
uploadArea.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
        isDemo = false;
    }
});

uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
        isDemo = false;
    }
});

// NEW: Sample Worksheet Button
sampleBtn.addEventListener('click', async () => {
    sampleBtn.disabled = true;
    sampleBtn.textContent = 'Loading sample...';
    
    try {
        // Use the existing frontend serving route
        const response = await fetch(`${API_BASE}/api/sample`);
        
        if (!response.ok) {
            throw new Error('Sample file not found');
        }
        
        const blob = await response.blob();
        const file = new File([blob], 'sample.png', { type: 'image/png' });
        
        handleFile(file);
        isDemo = true;
        
        // Auto-trigger split for demo
        setTimeout(() => {
            if (splitBtn && !splitBtn.disabled) {
                splitBtn.click();
            }
        }, 500);
        
    } catch (error) {
        console.error('Sample load error:', error);
        showError('Could not load sample. Please upload your own file.');
    } finally {
        sampleBtn.disabled = false;
        sampleBtn.textContent = '✨ See how it works with a sample worksheet';
    }
});

function handleFile(file) {
    selectedFile = file;
    
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    
    fileInfo.classList.add('show');
    splitBtn.classList.add('show');
    
    hideMessages();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function hideMessages() {
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
}

function showError(message) {
    hideMessages();
    errorMsg.textContent = '❌ ' + message;
    errorMsg.classList.add('show');
}

function showSuccess(message) {
    hideMessages();
    successMsg.textContent = '✅ ' + message;
    successMsg.classList.add('show');
}

function updateProgress(percent, text) {
    progressBar.style.width = percent + '%';
    progressText.textContent = text;
}

function showEmailModal() {
    modalOverlay.classList.add('show');
}

function hideEmailModal() {
    modalOverlay.classList.remove('show');
    emailInput.value = '';
    commentInput.value = '';
    marketingOptIn.checked = false;
}

function showViewer() {
    viewerOverlay.classList.add('show');
    updateViewerUI();
}

function hideViewer() {
    viewerOverlay.classList.remove('show');
}

function updateViewerUI() {
    if (processedQuestions.length === 0) return;
    
    const current = processedQuestions[currentQuestionIndex];
    
    // Update image
    viewerImage.src = current.imageUrl;
    
    // Update counter
    viewerCounter.textContent = `Question ${currentQuestionIndex + 1} of ${processedQuestions.length}`;
    
    // Update navigation buttons
    viewerPrev.disabled = currentQuestionIndex === 0;
    viewerNext.disabled = currentQuestionIndex === processedQuestions.length - 1;
}

function navigateQuestion(direction) {
    const newIndex = currentQuestionIndex + direction;
    
    if (newIndex >= 0 && newIndex < processedQuestions.length) {
        currentQuestionIndex = newIndex;
        updateViewerUI();
    }
}

async function extractQuestionsFromZip(blob) {
    try {
        // First, we need to load JSZip
        if (typeof JSZip === 'undefined') {
            // Load JSZip from CDN
            await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
        }
        
        const zip = new JSZip();
        const zipContent = await zip.loadAsync(blob);
        
        const questions = [];
        const pdfFiles = [];
        
        // Find all PDF files (excluding combined)
        zipContent.forEach((relativePath, zipEntry) => {
            if (relativePath.endsWith('.pdf') && !relativePath.includes('combined')) {
                pdfFiles.push({ name: relativePath, entry: zipEntry });
            }
        });
        
        // Sort by filename
        pdfFiles.sort((a, b) => a.name.localeCompare(b.name));
        
        console.log(`Found ${pdfFiles.length} question PDFs in ZIP`);
        
        // Extract each PDF and convert to image
        for (const pdfFile of pdfFiles) {
            const pdfBlob = await pdfFile.entry.async('blob');
            const imageUrl = await convertPdfToImage(pdfBlob);
            
            questions.push({
                name: pdfFile.name,
                imageUrl: imageUrl,
                blob: pdfBlob
            });
        }
        
        return questions;
        
    } catch (error) {
        console.error('Error extracting questions:', error);
        
        // Fallback: create placeholders
        const questionCount = pendingDownload.questionCount || 3;
        const questions = [];
        
        for (let i = 0; i < questionCount; i++) {
            questions.push({
                name: `question_${String(i + 1).padStart(2, '0')}.pdf`,
                imageUrl: createPlaceholderImage(i + 1),
                blob: blob
            });
        }
        
        return questions;
    }
}

async function convertPdfToImage(pdfBlob) {
    try {
        // Initialize PDF.js worker
        if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }
        
        // Load the PDF
        const arrayBuffer = await pdfBlob.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        
        // Get the first page
        const page = await pdf.getPage(1);
        
        // Set scale for good quality
        const scale = 2.0;
        const viewport = page.getViewport({ scale: scale });
        
        // Create canvas
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        canvas.height = viewport.height;
        canvas.width = viewport.width;
        
        // Render PDF page to canvas
        await page.render({
            canvasContext: context,
            viewport: viewport
        }).promise;
        
        // Convert canvas to data URL
        return canvas.toDataURL('image/png');
        
    } catch (error) {
        console.error('Error converting PDF to image:', error);
        return createPlaceholderImage(1);
    }
}

function createPlaceholderImage(questionNumber) {
    return 'data:image/svg+xml;base64,' + btoa(`
        <svg width="800" height="600" xmlns="http://www.w3.org/2000/svg">
            <rect width="800" height="600" fill="#f8f9ff"/>
            <text x="400" y="280" font-size="48" text-anchor="middle" fill="#667eea" font-family="Arial, sans-serif" font-weight="600">
                Question ${questionNumber}
            </text>
            <text x="400" y="340" font-size="20" text-anchor="middle" fill="#999" font-family="Arial, sans-serif">
                Loading preview...
            </text>
        </svg>
    `);
}

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
    });
}

function triggerDownload(blob, filename) {
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    a.style.display = 'none';
    
    document.body.appendChild(a);
    setTimeout(() => a.click(), 10);
    
    setTimeout(() => {
        if (document.body.contains(a)) {
            document.body.removeChild(a);
        }
        window.URL.revokeObjectURL(downloadUrl);
    }, 2000);
}

async function submitEmail(email, comment, marketingOptIn) {
    if (!email && !comment) return;

    try {
        const response = await fetch(`${API_BASE}/api/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email || "",
                comment: comment || "",
                marketing_opt_in: marketingOptIn || false,
                timestamp: new Date().toISOString()
            })
        });
        
        const data = await response.json();
        console.log('Feedback response:', data);
        
    } catch (error) {
        console.error('Feedback error:', error);
    }
}

// Modal Event Listeners
modalClose.addEventListener('click', () => {
    hideEmailModal();
    // Show viewer after closing modal
    if (pendingDownload && processedQuestions.length > 0) {
        showViewer();
    }
});

emailForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const email = emailInput.value.trim();
    const comment = commentInput.value.trim();
    const optIn = marketingOptIn.checked;
    
    submitEmail(email, comment, optIn);
    
    hideEmailModal();
    
    // Show viewer after email submission
    if (pendingDownload && processedQuestions.length > 0) {
        showViewer();
    }
});

// Viewer Event Listeners
viewerClose.addEventListener('click', hideViewer);

viewerPrev.addEventListener('click', () => navigateQuestion(-1));
viewerNext.addEventListener('click', () => navigateQuestion(1));

// Keyboard navigation in viewer
document.addEventListener('keydown', (e) => {
    if (!viewerOverlay.classList.contains('show')) return;
    
    if (e.key === 'ArrowLeft') {
        navigateQuestion(-1);
    } else if (e.key === 'ArrowRight') {
        navigateQuestion(1);
    } else if (e.key === 'Escape') {
        hideViewer();
    }
});

downloadCurrent.addEventListener('click', async () => {
    if (pendingDownload && processedQuestions.length > 0) {
        const currentQuestion = processedQuestions[currentQuestionIndex];
        
        // Download the individual PDF
        triggerDownload(currentQuestion.blob, currentQuestion.name);
        showSuccess(`Downloading ${currentQuestion.name}...`);
    }
});

downloadAll.addEventListener('click', () => {
    if (pendingDownload) {
        // Download the full ZIP file
        triggerDownload(pendingDownload.blob, pendingDownload.filename);
        showSuccess(`Downloading all ${processedQuestions.length} questions...`);
    }
});

// Split Button Handler
splitBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    splitBtn.disabled = true;
    progressContainer.classList.add('show');
    updateProgress(0, 'Preparing upload...');
    hideMessages();

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);

        const url = `${API_BASE}/api/split?dpi=150&conf_threshold=0.10`;

        console.log('Uploading to:', url);
        console.log('File:', selectedFile.name, selectedFile.size);

        // Simulate upload progress
        updateProgress(10, 'Uploading... 10%');
        
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 180000);

        // Start upload
        updateProgress(30, 'Uploading... 30%');
        
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
            // Don't buffer the response - start receiving immediately
            cache: 'no-store'
        });

        clearTimeout(timeoutId);
        
        updateProgress(50, 'Processing... 50%');

        console.log('Response status:', response.status);

        if (!response.ok) {
            let errorMsg = 'Something went wrong. Please try again.';
            try {
                const errorData = await response.json();
                errorMsg = errorData.detail || errorMsg;
            } catch (e) {
                if (response.status === 429) {
                    errorMsg = 'Too many requests. Please wait an hour and try again.';
                } else if (response.status === 413) {
                    errorMsg = 'File is too large. Maximum size is 20MB.';
                } else {
                    errorMsg = `Server error (${response.status}). Please try again.`;
                }
            }
            throw new Error(errorMsg);
        }

        updateProgress(70, 'Splitting questions... 70%');

        const questionCount = response.headers.get('X-Questions-Count');
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'questions.zip';
        
        if (contentDisposition) {
            const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (match && match[1]) {
                filename = match[1].replace(/['"]/g, '');
            }
        }

        console.log('Downloading:', filename, 'Questions:', questionCount);

        updateProgress(90, 'Finalizing... 90%');

        let blob;
        try {
            blob = await response.blob();
            console.log('Blob received:', blob.size, 'bytes');
        } catch (blobError) {
            console.error('Blob error:', blobError);
            throw new Error('Download failed. Please try again.');
        }
        
        if (blob.size === 0) {
            throw new Error('Received empty file. Please try again.');
        }

        updateProgress(100, 'Complete! 100%');

        pendingDownload = {
            blob: blob,
            filename: filename,
            questionCount: parseInt(questionCount) || 0
        };

        // Show loading message
        updateProgress(100, 'Preparing preview...');

        // Extract questions for viewer
        processedQuestions = await extractQuestionsFromZip(blob);
        currentQuestionIndex = 0;

        console.log(`Extracted ${processedQuestions.length} questions for preview`);

        // Hide progress, show success
        setTimeout(() => {
            progressContainer.classList.remove('show');
            
            if (isDemo) {
                // For demo, show viewer directly
                showViewer();
            } else {
                // For real files, show email modal first
                showEmailModal();
            }
        }, 500);

    } catch (error) {
        console.error('Error:', error);
        progressContainer.classList.remove('show');
        showError(error.message);
    } finally {
        setTimeout(() => {
            splitBtn.disabled = false;
        }, 1000);
    }
});

// Check backend on load
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data = await response.json();
        
        if (!data.model_ready) {
            showError('Service is temporarily unavailable. Please try again later.');
            uploadArea.style.opacity = '0.5';
            uploadArea.style.pointerEvents = 'none';
            sampleBtn.style.opacity = '0.5';
            sampleBtn.style.pointerEvents = 'none';
        }
    } catch (error) {
        console.error('Health check failed:', error);
    }
});