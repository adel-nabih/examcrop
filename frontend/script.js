// API Configuration
const API_BASE = (() => {
    const hostname = window.location.hostname;
    
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'http://localhost:8000';
    }
    
    if (hostname === 'examcrop.com' || hostname === 'www.examcrop.com') {
        return 'https://pdf-splitter-production-9d84.up.railway.app';
    }
    
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
const previewButtons = document.getElementById('previewButtons');
const previewOriginalBtn = document.getElementById('previewOriginalBtn');
const previewResultsBtn = document.getElementById('previewResultsBtn');
const progressContainer = document.getElementById('progressContainer');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const loading = document.getElementById('loading');
const errorMsg = document.getElementById('errorMsg');
const successMsg = document.getElementById('successMsg');

const modalOverlay = document.getElementById('modalOverlay');
const emailForm = document.getElementById('emailForm');
const emailInput = document.getElementById('emailInput');
const commentInput = document.getElementById('commentInput');
const marketingOptIn = document.getElementById('marketingOptIn');

const viewerOverlay = document.getElementById('viewerOverlay');
const viewerClose = document.getElementById('viewerClose');
const viewerImage = document.getElementById('viewerImage');
const viewerTitle = document.getElementById('viewerTitle');
const viewerCounter = document.getElementById('viewerCounter');
const viewerPrev = document.getElementById('viewerPrev');
const viewerNext = document.getElementById('viewerNext');
const downloadCurrent = document.getElementById('downloadCurrent');
const downloadAll = document.getElementById('downloadAll');

// Page selector
const pageSelector      = document.getElementById('pageSelector');
const pageSelectorTotal = document.getElementById('pageSelectorTotal');
const pageRangeAll      = document.getElementById('pageRangeAll');
const pageRangeCustom   = document.getElementById('pageRangeCustom');
const pageRangeInputWrap= document.getElementById('pageRangeInputWrap');
const pageRangeInput    = document.getElementById('pageRangeInput');
const pageRangeError    = document.getElementById('pageRangeError');

// Viewer trash
const viewerTrash = document.getElementById('viewerTrash');

// State
let selectedFile = null;
let originalFilePages = [];
let pendingDownload = null;
let processedQuestions = [];  // now holds one entry per page of the combined PDF
let currentQuestionIndex = 0;
let currentViewMode = 'results';
let isDemo = false;

// ── Page selector helpers ────────────────────────────────────────────────

let pageSelectorMode = 'all'; // 'all' | 'custom'

pageRangeAll.addEventListener('click', () => {
    pageSelectorMode = 'all';
    pageRangeAll.classList.add('active');
    pageRangeCustom.classList.remove('active');
    pageRangeInputWrap.classList.remove('show');
    pageRangeError.classList.remove('show');
});

pageRangeCustom.addEventListener('click', () => {
    pageSelectorMode = 'custom';
    pageRangeCustom.classList.add('active');
    pageRangeAll.classList.remove('active');
    pageRangeInputWrap.classList.add('show');
    pageRangeInput.focus();
});

/**
 * Parse a page range string like "1-5, 7, 9-12" into a sorted unique array.
 * Returns null if the input is invalid.
 */
function parsePageRange(str, totalPages) {
    const parts = str.split(',').map(s => s.trim()).filter(Boolean);
    const pages = new Set();

    for (const part of parts) {
        if (/^\d+$/.test(part)) {
            const n = parseInt(part);
            if (n < 1 || n > totalPages) return null;
            pages.add(n);
        } else if (/^\d+-\d+$/.test(part)) {
            const [a, b] = part.split('-').map(Number);
            if (a < 1 || b > totalPages || a > b) return null;
            for (let i = a; i <= b; i++) pages.add(i);
        } else {
            return null;
        }
    }

    return pages.size > 0 ? [...pages].sort((a, b) => a - b) : null;
}

// ── Smooth scroll
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

// Sample Button
sampleBtn.addEventListener('click', async () => {
    sampleBtn.disabled = true;
    sampleBtn.textContent = 'Loading sample...';
    
    try {
        const response = await fetch(`${API_BASE}/api/sample`);
        
        if (!response.ok) {
            throw new Error('Sample file not found');
        }
        
        const blob = await response.blob();
        const file = new File([blob], 'sample.png', { type: 'image/png' });
        
        handleFile(file);
        isDemo = true;
        
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

async function handleFile(file) {
    selectedFile = file;
    
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    
    fileInfo.classList.add('show');
    splitBtn.classList.add('show');

    // Reset state from any previous upload
    previewButtons.classList.remove('show');
    processedQuestions = [];
    pendingDownload = null;
    currentQuestionIndex = 0;

    // Reset page selector
    pageSelectorMode = 'all';
    pageRangeAll.classList.add('active');
    pageRangeCustom.classList.remove('active');
    pageRangeInputWrap.classList.remove('show');
    pageRangeInput.value = '';
    pageRangeError.classList.remove('show');
    pageSelector.classList.remove('show');
    
    hideMessages();
    
    await loadOriginalFilePages(file);
}

async function loadOriginalFilePages(file) {
    try {
        originalFilePages = [];
        
        if (file.type === 'application/pdf') {
            const arrayBuffer = await file.arrayBuffer();
            
            if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            }
            
            const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
            const pageCount = pdf.numPages;
            
            console.log(`Loading ${pageCount} pages from original PDF`);
            
            for (let i = 1; i <= pageCount; i++) {
                const page = await pdf.getPage(i);
                const scale = 2.0;
                const viewport = page.getViewport({ scale: scale });
                
                const canvas = document.createElement('canvas');
                const context = canvas.getContext('2d');
                canvas.height = viewport.height;
                canvas.width = viewport.width;
                
                await page.render({
                    canvasContext: context,
                    viewport: viewport
                }).promise;
                
                originalFilePages.push({
                    pageNumber: i,
                    imageUrl: canvas.toDataURL('image/png')
                });
            }
            
            console.log(`Loaded ${originalFilePages.length} pages`);

            // Show page selector for multi-page PDFs
            if (pageCount > 1) {
                pageSelectorTotal.textContent = `${pageCount} pages total`;
                pageSelector.classList.add('show');
            }
            
        } else if (file.type.startsWith('image/')) {
            const imageUrl = await readFileAsDataURL(file);
            originalFilePages.push({
                pageNumber: 1,
                imageUrl: imageUrl
            });
            
            console.log('Loaded single image file');
        }
        
    } catch (error) {
        console.error('Error loading original file:', error);
    }
}

function readFileAsDataURL(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
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

function showViewer(mode = 'results') {
    currentViewMode = mode;
    viewerOverlay.classList.add('show');
    
    if (mode === 'original') {
        viewerTitle.textContent = 'Original File Preview';
        currentQuestionIndex = 0;
        updateOriginalViewerUI();
    } else {
        viewerTitle.textContent = 'Questions Preview';
        currentQuestionIndex = 0;
        updateResultsViewerUI();
    }
}

function hideViewer() {
    viewerOverlay.classList.remove('show');
}

function updateOriginalViewerUI() {
    if (originalFilePages.length === 0) return;
    
    const current = originalFilePages[currentQuestionIndex];
    viewerImage.src = current.imageUrl;
    
    if (originalFilePages.length > 1) {
        viewerCounter.textContent = `Page ${current.pageNumber} of ${originalFilePages.length}`;
    } else {
        viewerCounter.textContent = 'Single page';
    }
    
    viewerPrev.disabled = currentQuestionIndex === 0;
    viewerNext.disabled = currentQuestionIndex === originalFilePages.length - 1;
    
    downloadCurrent.style.display = 'none';
    downloadAll.textContent = 'Download Original';
    viewerTrash.classList.add('hidden');
}

function updateResultsViewerUI() {
    if (processedQuestions.length === 0) return;
    
    const current = processedQuestions[currentQuestionIndex];
    viewerImage.src = current.imageUrl;
    
    // Label each page as a question (1-indexed)
    viewerCounter.textContent = `Question ${currentQuestionIndex + 1} of ${processedQuestions.length}`;
    
    viewerPrev.disabled = currentQuestionIndex === 0;
    viewerNext.disabled = currentQuestionIndex === processedQuestions.length - 1;
    
    // Hide per-question download since we only have the combined PDF now
    downloadCurrent.style.display = 'none';
    downloadAll.textContent = `Download All Questions (PDF)`;
    viewerTrash.classList.remove('hidden');
}

function navigateQuestion(direction) {
    const newIndex = currentQuestionIndex + direction;
    const maxIndex = currentViewMode === 'original'
        ? originalFilePages.length - 1
        : processedQuestions.length - 1;
    
    if (newIndex >= 0 && newIndex <= maxIndex) {
        currentQuestionIndex = newIndex;
        
        if (currentViewMode === 'original') {
            updateOriginalViewerUI();
        } else {
            updateResultsViewerUI();
        }
    }
}

/**
 * Extract the combined PDF from the ZIP, then render every page
 * into processedQuestions as individual image entries.
 */
async function extractQuestionsFromZip(blob) {
    try {
        if (typeof JSZip === 'undefined') {
            await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
        }
        
        if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }

        const zip = new JSZip();
        const zipContent = await zip.loadAsync(blob);

        // Pull out the combined PDF — it's the only PDF in the ZIP now
        let combinedEntry = null;
        zipContent.forEach((relativePath, zipEntry) => {
            if (relativePath.endsWith('.pdf')) {
                combinedEntry = zipEntry;
            }
        });

        if (!combinedEntry) {
            throw new Error('Combined PDF not found in ZIP');
        }

        const combinedBlob = await combinedEntry.async('blob');
        const arrayBuffer  = await combinedBlob.arrayBuffer();
        const pdf          = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;

        console.log(`Rendering ${pdf.numPages} pages from combined PDF`);

        const pages = [];
        for (let i = 1; i <= pdf.numPages; i++) {
            const page     = await pdf.getPage(i);
            const scale    = 2.0;
            const viewport = page.getViewport({ scale });

            const canvas  = document.createElement('canvas');
            canvas.width  = viewport.width;
            canvas.height = viewport.height;

            await page.render({
                canvasContext: canvas.getContext('2d'),
                viewport
            }).promise;

            pages.push({
                pageNumber: i,
                imageUrl:   canvas.toDataURL('image/png'),
            });
        }

        return pages;

    } catch (error) {
        console.error('Error extracting combined PDF:', error);

        // Fallback: single placeholder so the viewer still opens
        return [{
            pageNumber: 1,
            imageUrl:   createPlaceholderImage(1),
        }];
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

// Modal Event Listeners — no close button, email required to download

emailForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const email   = emailInput.value.trim();
    const comment = commentInput.value.trim();
    const optIn   = marketingOptIn.checked;

    submitEmail(email, comment, optIn);
    hideEmailModal();

    // Trigger the actual download now that email is collected
    if (pendingDownload) {
        triggerDownload(pendingDownload.blob, pendingDownload.filename);
        showSuccess(`Downloading ${processedQuestions.length} questions...`);
    }
});

// Preview Button Listeners
previewOriginalBtn.addEventListener('click', () => {
    if (originalFilePages.length > 0) {
        showViewer('original');
    }
});

previewResultsBtn.addEventListener('click', () => {
    if (processedQuestions.length > 0) {
        showViewer('results');
    }
});

// Viewer Event Listeners
viewerClose.addEventListener('click', hideViewer);

// Trash — remove current question from results
viewerTrash.addEventListener('click', () => {
    if (processedQuestions.length <= 1) {
        // Don't allow deleting the last question
        viewerTrash.style.animation = 'none';
        viewerTrash.textContent = '⚠️';
        setTimeout(() => { viewerTrash.textContent = '🗑'; }, 1000);
        return;
    }

    processedQuestions.splice(currentQuestionIndex, 1);

    // Adjust index if we deleted the last item
    if (currentQuestionIndex >= processedQuestions.length) {
        currentQuestionIndex = processedQuestions.length - 1;
    }

    updateResultsViewerUI();
});

viewerPrev.addEventListener('click', () => navigateQuestion(-1));
viewerNext.addEventListener('click', () => navigateQuestion(1));

document.addEventListener('keydown', (e) => {
    if (!viewerOverlay.classList.contains('show')) return;
    if (e.key === 'ArrowLeft')  navigateQuestion(-1);
    if (e.key === 'ArrowRight') navigateQuestion(1);
    if (e.key === 'Escape')     hideViewer();
});

// "Download This Question" hidden — only combined PDF download available
downloadCurrent.addEventListener('click', () => {
    if (pendingDownload) {
        triggerDownload(pendingDownload.blob, pendingDownload.filename);
    }
});

downloadAll.addEventListener('click', () => {
    if (currentViewMode === 'original' && selectedFile) {
        // Original file — no gate
        triggerDownload(selectedFile, selectedFile.name);
        showSuccess('Downloading original file...');
    } else if (pendingDownload) {
        // Gate results download behind email
        hideViewer();
        showEmailModal();
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

        // Validate and apply page range if custom mode
        let pageRangeParam = '';
        if (pageSelectorMode === 'custom' && !isDemo) {
            const totalPages = originalFilePages.length;
            const parsed = parsePageRange(pageRangeInput.value, totalPages);
            if (!parsed) {
                pageRangeError.textContent = `Invalid range. Enter page numbers between 1 and ${totalPages}.`;
                pageRangeError.classList.add('show');
                splitBtn.disabled = false;
                progressContainer.classList.remove('show');
                return;
            }
            pageRangeError.classList.remove('show');
            pageRangeParam = `&pages=${parsed.join(',')}`;
        }

        const url = `${API_BASE}/api/split?dpi=200&conf_threshold=0.10${isDemo ? '&is_sample=true' : ''}${pageRangeParam}`;

        console.log('Uploading to:', url);
        console.log('File:', selectedFile.name, selectedFile.size);

        updateProgress(10, 'Uploading... 10%');
        
        const controller = new AbortController();
        const timeoutId  = setTimeout(() => controller.abort(), 180000);

        updateProgress(30, 'Uploading... 30%');
        
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
            cache: 'no-store'
        });

        clearTimeout(timeoutId);
        updateProgress(50, 'Processing... 50%');

        console.log('Response status:', response.status);

        if (!response.ok) {
            let errText = 'Something went wrong. Please try again.';
            try {
                const errorData = await response.json();
                errText = errorData.detail || errText;
            } catch (e) {
                if (response.status === 429) {
                    errText = 'Too many requests. Please wait an hour and try again.';
                } else if (response.status === 413) {
                    errText = 'File is too large. Maximum size is 20MB.';
                } else {
                    errText = `Server error (${response.status}). Please try again.`;
                }
            }
            throw new Error(errText);
        }

        updateProgress(70, 'Splitting questions... 70%');

        const questionCount      = response.headers.get('X-Questions-Count');
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
            blob:          blob,
            filename:      filename,
            questionCount: parseInt(questionCount) || 0
        };

        updateProgress(100, 'Preparing preview...');

        processedQuestions  = await extractQuestionsFromZip(blob);
        currentQuestionIndex = 0;

        console.log(`Rendered ${processedQuestions.length} pages for preview`);

        setTimeout(() => {
            progressContainer.classList.remove('show');
            previewButtons.classList.add('show');

            if (isDemo) {
                showViewer('results');
            } else {
                // Open viewer directly — email gate fires on download
                showViewer('results');
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

// Health check on load
window.addEventListener('DOMContentLoaded', async () => {
    try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data     = await response.json();
        
        if (!data.model_ready) {
            showError('Service is temporarily unavailable. Please try again later.');
            uploadArea.style.opacity      = '0.5';
            uploadArea.style.pointerEvents = 'none';
            sampleBtn.style.opacity       = '0.5';
            sampleBtn.style.pointerEvents  = 'none';
        }
    } catch (error) {
        console.error('Health check failed:', error);
    }
});