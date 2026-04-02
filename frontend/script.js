// API Configuration
const API_BASE = (() => {
    const hostname = window.location.hostname;
    
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return 'http://localhost:8080';
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
const saveBankBtn = document.getElementById('saveBankBtn');

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
let _bankSaved = false;

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
        const href = this.getAttribute('href');
        if (!href || href === '#' || !href.startsWith('#')) return;
        const target = document.querySelector(href);
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
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
    _bankSaved = false;

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
    const savedEmail = localStorage.getItem('examcrop_email');
    if (savedEmail) {
        // Returning user — skip modal, log the upload linkage silently, download
        submitEmail(savedEmail, '', false);
        if (pendingDownload) {
            buildAndDownloadPdf();
        }
        return;
    }
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
        // Trigger feedback toast after user has had time to review
        if (window._lastUploadId) {
            showFeedbackToast(window._lastUploadId);
        }
    }
    updateSaveBankBtn();
}

function hideViewer() {
    viewerOverlay.classList.remove('show');
    hideToast();
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

        // Render all pages in parallel for speed
        const renderPage = async (i) => {
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

            return {
                pageNumber: i,
                imageUrl:   canvas.toDataURL('image/png'),
            };
        };

        const pagePromises = [];
        for (let i = 1; i <= pdf.numPages; i++) {
            pagePromises.push(renderPage(i));
        }

        // Promise.all preserves order
        const pages = await Promise.all(pagePromises);
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
                email:            email || "",
                comment:          comment || "",
                marketing_opt_in: marketingOptIn || false,
                timestamp:        new Date().toISOString(),
                upload_id:        window._lastUploadId || "",
                is_returning:     !!localStorage.getItem('examcrop_email'),
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
    localStorage.setItem('examcrop_email', email);
    hideEmailModal();

    // Rebuild PDF from surviving pages then download
    if (pendingDownload && processedQuestions.length > 0) {
        buildAndDownloadPdf();
    }
});

/**
 * Re-render the current processedQuestions into a fresh PDF using pdf-lib,
 * falling back to the original ZIP blob if pdf-lib is unavailable.
 */
async function buildAndDownloadPdf() {
    try {
        // Load pdf-lib on demand
        if (typeof PDFLib === 'undefined') {
            await loadScript('https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js');
        }

        if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
            pdfjsLib.GlobalWorkerOptions.workerSrc =
                'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }

        // Extract the combined PDF blob from the ZIP
        if (typeof JSZip === 'undefined') {
            await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
        }

        const zip        = new JSZip();
        const zipContent = await zip.loadAsync(pendingDownload.blob);

        let combinedEntry = null;
        zipContent.forEach((relativePath, entry) => {
            if (relativePath.endsWith('.pdf')) combinedEntry = entry;
        });

        if (!combinedEntry) throw new Error('Combined PDF not found');

        const combinedBlob  = await combinedEntry.async('blob');
        const combinedBytes = new Uint8Array(await combinedBlob.arrayBuffer());

        // Build a new PDF containing only the surviving pages
        const { PDFDocument } = PDFLib;
        const srcDoc = await PDFDocument.load(combinedBytes);
        const outDoc = await PDFDocument.create();

        // processedQuestions[i].pageNumber is 1-indexed within the combined PDF
        const survivingIndexes = processedQuestions.map(q => q.pageNumber - 1);
        console.log('Surviving page indexes:', survivingIndexes);

        const copied = await outDoc.copyPages(srcDoc, survivingIndexes);
        copied.forEach(page => outDoc.addPage(page));

        const outBytes = await outDoc.save();
        const outBlob  = new Blob([outBytes], { type: 'application/pdf' });

        const baseName = pendingDownload.filename.replace('_questions.zip', '');
        triggerDownload(outBlob, `${baseName}_questions.pdf`);
        showSuccess(`Downloaded ${processedQuestions.length} question${processedQuestions.length !== 1 ? 's' : ''} as PDF`);

    } catch (err) {
        console.error('PDF rebuild failed, falling back to original ZIP:', err);
        triggerDownload(pendingDownload.blob, pendingDownload.filename);
        showSuccess(`Downloading questions...`);
    }
}

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
        // Can't delete the last page — flash the button
        viewerTrash.style.borderColor = 'rgba(220,53,69,0.8)';
        viewerTrash.style.boxShadow   = '0 0 12px rgba(220,53,69,0.5)';
        setTimeout(() => {
            viewerTrash.style.borderColor = '';
            viewerTrash.style.boxShadow   = '';
        }, 800);
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

// ── Save to Bank ──────────────────────────────────────────────────────────────

function updateSaveBankBtn() {
    if (!saveBankBtn) return;
    const hasResult = currentViewMode === 'results' && processedQuestions.length > 0 && window._lastUploadId;
    if (!hasResult) {
        saveBankBtn.style.display = 'none';
        return;
    }
    saveBankBtn.style.display = '';
    const loggedIn = window.Auth && window.Auth.isLoggedIn();
    if (!loggedIn && !_bankSaved) {
        saveBankBtn.textContent = '💾 Save to Bank';
        saveBankBtn.classList.remove('saved');
        saveBankBtn.disabled = false;
    }
}

async function _doSaveToBank(retryCount = 0) {
    const token    = window.Auth && window.Auth.getToken();
    const uploadId = window._lastUploadId;
    if (!token || !uploadId || _bankSaved) return;

    saveBankBtn.disabled    = true;
    saveBankBtn.textContent = retryCount > 0 ? 'Preparing…' : 'Saving...';

    try {
        const res = await fetch(`${API_BASE}/api/save-questions`, {
            method:  'POST',
            headers: {
                'Content-Type':  'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ upload_id: uploadId }),
        });

        // R2 upload still in progress — retry up to 6 times (30s total)
        if (res.status === 404 && retryCount < 6) {
            saveBankBtn.textContent = 'Preparing files…';
            setTimeout(() => _doSaveToBank(retryCount + 1), 5000);
            return;
        }

        if (res.status === 409) {
            _bankSaved = true;
            saveBankBtn.textContent = '✓ Already in Bank';
            saveBankBtn.classList.add('saved');
            saveBankBtn.disabled = false;
            return;
        }

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Save failed');
        }

        _bankSaved = true;
        saveBankBtn.textContent = '✓ Saved to Bank';
        saveBankBtn.classList.add('saved');
        saveBankBtn.disabled = false;

    } catch (err) {
        console.error('Save to Bank error:', err);
        saveBankBtn.textContent = '💾 Save to Bank';
        saveBankBtn.disabled    = false;
    }
}

// Expose globally so auth.js can trigger save after login
window._doSaveToBank = _doSaveToBank;

if (saveBankBtn) {
    saveBankBtn.addEventListener('click', async () => {
        const loggedIn = window.Auth && window.Auth.isLoggedIn();
        if (!loggedIn) {
            window._pendingSaveAfterAuth = true;
            // Close viewer so modal appears on top, viewer reopens after save
            if (typeof hideViewer === 'function') hideViewer();
            if (typeof showAuthModal === 'function') {
                showAuthModal('signup');
            }
            return;
        }
        await _doSaveToBank();
    });
}

// ── Split feedback toast ──────────────────────────────────────────────────────

// Inject toast styles once
(function injectToastStyles() {
    const style = document.createElement('style');
    style.textContent = `
        #splitFeedbackToast {
            position: fixed;
            bottom: 32px;
            left: 50%;
            transform: translateX(-50%) translateY(120px);
            background: #1A1812;
            border: 1.5px solid rgba(196,185,154,0.35);
            border-radius: 20px;
            padding: 18px 22px;
            z-index: 2000;
            box-shadow: 0 12px 48px rgba(0,0,0,0.55), 0 2px 8px rgba(0,0,0,0.3);
            transition: transform 0.35s cubic-bezier(0.34,1.56,0.64,1), opacity 0.25s;
            opacity: 0;
            min-width: 340px;
            max-width: calc(100vw - 40px);
            font-family: 'Inter', sans-serif;
        }
        #splitFeedbackToast.show {
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }
        .toast-row {
            display: flex;
            align-items: center;
            gap: 14px;
        }
        .toast-label {
            flex: 1;
            font-size: 15px;
            font-weight: 600;
            color: rgba(255,255,255,0.92);
            white-space: nowrap;
        }
        .toast-thumb {
            background: rgba(255,255,255,0.1);
            border: 1.5px solid rgba(255,255,255,0.15);
            border-radius: 10px;
            width: 44px; height: 44px;
            display: flex; align-items: center; justify-content: center;
            font-size: 20px;
            cursor: pointer;
            transition: background 0.15s, transform 0.15s;
            flex-shrink: 0;
        }
        .toast-thumb:hover { background: rgba(255,255,255,0.2); transform: scale(1.12); }
        .toast-dismiss {
            background: none; border: none;
            color: rgba(255,255,255,0.35);
            font-size: 20px; cursor: pointer;
            padding: 0 2px; line-height: 1;
            transition: color 0.15s;
            flex-shrink: 0;
        }
        .toast-dismiss:hover { color: rgba(255,255,255,0.7); }
        .toast-expand {
            margin-top: 14px;
            padding-top: 14px;
            border-top: 1px solid rgba(255,255,255,0.1);
            display: none;
        }
        .toast-expand.show { display: block; }
        .toast-select {
            width: 100%;
            padding: 10px 12px;
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 10px;
            color: rgba(255,255,255,0.85);
            font-size: 14px;
            font-family: 'Inter', sans-serif;
            outline: none;
            margin-bottom: 10px;
            cursor: pointer;
            appearance: none;
        }
        .toast-select option { background: #1A1812; }
        .toast-textarea {
            width: 100%;
            padding: 10px 12px;
            background: rgba(255,255,255,0.07);
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 10px;
            color: rgba(255,255,255,0.85);
            font-size: 14px;
            font-family: 'Inter', sans-serif;
            outline: none;
            resize: none;
            height: 68px;
            margin-bottom: 10px;
            box-sizing: border-box;
        }
        .toast-textarea::placeholder { color: rgba(255,255,255,0.3); }
        .toast-submit {
            width: 100%;
            padding: 11px;
            background: #3D6B35;
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 700;
            font-family: 'Plus Jakarta Sans', sans-serif;
            cursor: pointer;
            transition: background 0.15s;
            letter-spacing: -0.1px;
        }
        .toast-submit:hover { background: #2E5228; }
        .toast-thanks {
            text-align: center;
            font-size: 14px;
            color: rgba(255,255,255,0.65);
            padding: 4px 0 2px;
            display: none;
        }
    `;
    document.head.appendChild(style);
})();

// Build toast DOM once — deferred until DOM is ready
function _buildToast() {
    if (document.getElementById('splitFeedbackToast')) return;
    const el = document.createElement('div');
    el.id = 'splitFeedbackToast';
    el.innerHTML = `
        <div class="toast-row">
            <span class="toast-label">How did the split look?</span>
            <button class="toast-thumb" id="toastThumbUp" title="Looks good">👍</button>
            <button class="toast-thumb" id="toastThumbDown" title="Something's off">👎</button>
            <button class="toast-dismiss" id="toastDismiss" title="Dismiss">×</button>
        </div>
        <div class="toast-expand" id="toastExpand">
            <select class="toast-select" id="toastSelect">
                <option value="">What went wrong?</option>
                <option value="missed_question">Missed a question</option>
                <option value="wrong_split">Split in the wrong place</option>
                <option value="combined_questions">Combined two questions</option>
                <option value="extra_detection">Detected something that isn't a question</option>
                <option value="other">Other</option>
            </select>
            <textarea class="toast-textarea" id="toastTextarea" placeholder="Any extra detail? (optional)"></textarea>
            <button class="toast-submit" id="toastSubmit">Send feedback</button>
        </div>
        <div class="toast-thanks" id="toastThanks">Thanks — this helps us improve 🙏</div>
    `;
    document.body.appendChild(el);

    document.getElementById('toastDismiss').addEventListener('click', hideToast);

    document.getElementById('toastThumbUp').addEventListener('click', () => {
        submitRating('good', '');
        showToastThanks();
    });

    document.getElementById('toastThumbDown').addEventListener('click', () => {
        document.getElementById('toastExpand').classList.add('show');
        document.getElementById('toastThumbUp').style.display   = 'none';
        document.getElementById('toastThumbDown').style.display = 'none';
    });

    document.getElementById('toastSubmit').addEventListener('click', () => {
        const select   = document.getElementById('toastSelect').value;
        const text     = document.getElementById('toastTextarea').value.trim();
        const feedback = [select, text].filter(Boolean).join(' — ');
        submitRating('bad', feedback);
        showToastThanks();
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _buildToast);
} else {
    _buildToast();
}

let _toastTimer      = null;
let _toastUploadId   = null;
let _toastShownFor   = null;

function showFeedbackToast(uploadId) {
    if (!uploadId || _toastShownFor === uploadId) return;
    _toastShownFor = uploadId;
    _toastUploadId = uploadId;

    // Reset state
    document.getElementById('toastExpand').classList.remove('show');
    document.getElementById('toastThanks').style.display      = 'none';
    document.getElementById('toastThumbUp').style.display     = '';
    document.getElementById('toastThumbDown').style.display   = '';
    document.getElementById('toastSelect').value              = '';
    document.getElementById('toastTextarea').value            = '';

    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
        document.getElementById('splitFeedbackToast').classList.add('show');
    }, 5000); // 5 seconds after viewer opens
}

function hideToast() {
    clearTimeout(_toastTimer);
    document.getElementById('splitFeedbackToast').classList.remove('show');
}

function showToastThanks() {
    document.getElementById('toastExpand').classList.remove('show');
    document.getElementById('toastThanks').style.display = 'block';
    setTimeout(hideToast, 2500);
}

async function submitRating(rating, feedback) {
    const uploadId = _toastUploadId;
    if (!uploadId) return;
    try {
        await fetch(`${API_BASE}/api/uploads/${uploadId}/rating`, {
            method:  'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ rating, feedback }),
        });
    } catch (e) {
        console.error('Rating submit failed:', e);
    }
}
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

        const savedEmail  = localStorage.getItem('examcrop_email') || '';
        const isReturning = !!savedEmail;
        const sourcePage  = window.EXAMCROP_SOURCE_PAGE || 'home';
        const returningParam = isReturning ? `&returning_email=${encodeURIComponent(savedEmail)}` : '';
        const url = `${API_BASE}/api/split?dpi=150&conf_threshold=0.10${isDemo ? '&is_sample=true' : ''}${pageRangeParam}&is_returning=${isReturning}${returningParam}&source_page=${sourcePage}`;

        console.log('Uploading to:', url);
        console.log('File:', selectedFile.name, selectedFile.size);

        updateProgress(15, 'Uploading...');

        const controller = new AbortController();
        const timeoutId  = setTimeout(() => controller.abort(), 180000);

        updateProgress(30, 'Uploading...');

        // Smooth progress animation while server processes — crawls 30→88% over ~12s
        let _animPct = 30;
        const _animInterval = setInterval(() => {
            const remaining = 88 - _animPct;
            _animPct += remaining * 0.06; // decelerates as it approaches 88
            const labels = [
                [40, 'Analysing pages...'],
                [55, 'Detecting questions...'],
                [70, 'Splitting...'],
                [82, 'Almost done...'],
            ];
            const label = [...labels].reverse().find(([pct]) => _animPct >= pct)?.[1] || 'Processing...';
            updateProgress(Math.min(_animPct, 88), label);
        }, 200);

        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
            cache: 'no-store'
        });

        clearInterval(_animInterval);
        clearTimeout(timeoutId);
        updateProgress(92, 'Finalizing...');

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

        updateProgress(95, 'Preparing preview...');

        const questionCount      = response.headers.get('X-Questions-Count');
        const uploadId           = response.headers.get('X-Upload-Id');
        if (uploadId) window._lastUploadId = uploadId;
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'questions.zip';
        
        if (contentDisposition) {
            const match = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
            if (match && match[1]) {
                filename = match[1].replace(/['"]/g, '');
            }
        }

        console.log('Downloading:', filename, 'Questions:', questionCount);
        updateProgress(100, 'Complete!');
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
        clearInterval(typeof _animInterval !== 'undefined' ? _animInterval : null);
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