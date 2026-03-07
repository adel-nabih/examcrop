// ── API ─────────────────────────────────────────────────────────────────────
const API_BASE = (() => {
    const h = window.location.hostname;
    if (h === 'localhost' || h === '127.0.0.1') return 'http://localhost:8000';
    if (h === 'examcrop.com' || h === 'www.examcrop.com') return 'https://pdf-splitter-production-9d84.up.railway.app';
    return '';
})();

// ── Navbar ──────────────────────────────────────────────────────────────────
const mainHeader = document.getElementById('mainHeader');
window.addEventListener('scroll', () => mainHeader.classList.toggle('scrolled', window.scrollY > 60));

const hamburger  = document.getElementById('hamburger');
const mobileMenu = document.getElementById('mobileMenu');
hamburger.addEventListener('click', () => {
    hamburger.classList.toggle('open');
    mobileMenu.classList.toggle('open');
});
document.querySelectorAll('.mobile-nav-link').forEach(l => l.addEventListener('click', () => {
    hamburger.classList.remove('open');
    mobileMenu.classList.remove('open');
}));

// ── Curriculum dropdown ──────────────────────────────────────────────────────
const curriculumDropdown = document.getElementById('curriculumDropdown');
const curriculumTrigger  = document.getElementById('curriculumTrigger');

curriculumTrigger.addEventListener('click', e => {
    e.stopPropagation();
    curriculumDropdown.classList.toggle('open');
});
document.addEventListener('click', () => curriculumDropdown.classList.remove('open'));
curriculumDropdown.querySelector('.dropdown-menu').addEventListener('click', e => e.stopPropagation());
document.addEventListener('keydown', e => { if (e.key === 'Escape') curriculumDropdown.classList.remove('open'); });

// ── FAQ accordion ────────────────────────────────────────────────────────────
function toggleFaq(btn) {
    const answer = btn.nextElementSibling;
    const isOpen = btn.getAttribute('aria-expanded') === 'true';
    document.querySelectorAll('.faq-q').forEach(b => {
        b.setAttribute('aria-expanded', 'false');
        b.nextElementSibling.classList.remove('open');
    });
    if (!isOpen) {
        btn.setAttribute('aria-expanded', 'true');
        answer.classList.add('open');
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function loadScript(src) {
    return new Promise((res, rej) => {
        const s = document.createElement('script');
        s.src = src; s.onload = res; s.onerror = rej;
        document.head.appendChild(s);
    });
}

function formatSize(b) {
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1024 / 1024).toFixed(1) + ' MB';
}

function parsePageRange(str, total) {
    const parts = str.split(',').map(s => s.trim()).filter(Boolean);
    const pages = new Set();
    for (const p of parts) {
        if (/^\d+$/.test(p)) {
            const n = parseInt(p);
            if (n < 1 || n > total) return null;
            pages.add(n);
        } else if (/^\d+-\d+$/.test(p)) {
            const [a, b] = p.split('-').map(Number);
            if (a < 1 || b > total || a > b) return null;
            for (let i = a; i <= b; i++) pages.add(i);
        } else return null;
    }
    return pages.size > 0 ? [...pages].sort((a, b) => a - b) : null;
}

async function extractPages(zipBlob) {
    if (typeof JSZip === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');
    if (!pdfjsLib.GlobalWorkerOptions.workerSrc)
        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
    const zip = new JSZip();
    await zip.loadAsync(zipBlob);
    let entry = null;
    zip.forEach((p, e) => { if (p.endsWith('.pdf')) entry = e; });
    if (!entry) return [];
    const pdfBytes = await entry.async('arraybuffer');
    const pdf = await pdfjsLib.getDocument({ data: pdfBytes }).promise;
    return Promise.all(Array.from({ length: pdf.numPages }, async (_, i) => {
        const page = await pdf.getPage(i + 1);
        const vp = page.getViewport({ scale: 1.8 });
        const canvas = document.createElement('canvas');
        canvas.width = vp.width; canvas.height = vp.height;
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
        return canvas.toDataURL('image/png');
    }));
}

// ── Before/After viewer ──────────────────────────────────────────────────────
// AFTER_PAGES is defined per-page as a const before this script runs.
// renderAfter / afterNav are defined inline per-page to allow base64 injection.

// ── Upload tool ──────────────────────────────────────────────────────────────
let selectedFile = null, pendingBlob = null, pendingFilename = null;
let processedQuestions = [], currentQuestionIndex = 0;
let pageSelectorMode = 'all', originalPageCount = 0;
let _bankSaved = false;

const uploadArea        = document.getElementById('uploadArea');
const fileInput         = document.getElementById('fileInput');
const fileInfo          = document.getElementById('fileInfo');
const fileNameEl        = document.getElementById('fileName');
const fileSizeEl        = document.getElementById('fileSize');
const splitBtn          = document.getElementById('splitBtn');
const progressCont      = document.getElementById('progressContainer');
const progressBar       = document.getElementById('progressBar');
const progressText      = document.getElementById('progressText');
const errorMsg          = document.getElementById('errorMsg');
const successMsg        = document.getElementById('successMsg');
const viewerOverlay     = document.getElementById('viewerOverlay');
const viewerClose       = document.getElementById('viewerClose');
const viewerImage       = document.getElementById('viewerImage');
const viewerTitle       = document.getElementById('viewerTitle');
const viewerCounter     = document.getElementById('viewerCounter');
const viewerPrev        = document.getElementById('viewerPrev');
const viewerNext        = document.getElementById('viewerNext');
const viewerTrash       = document.getElementById('viewerTrash');
const downloadAll       = document.getElementById('downloadAll');
const saveBankBtn       = document.getElementById('saveBankBtn');
const modalOverlay      = document.getElementById('modalOverlay');
const emailForm         = document.getElementById('emailForm');
const emailInput        = document.getElementById('emailInput');
const pageSelector      = document.getElementById('pageSelector');
const pageTotalEl       = document.getElementById('pageSelectorTotal');
const pageRangeAll      = document.getElementById('pageRangeAll');
const pageRangeCustom   = document.getElementById('pageRangeCustom');
const pageRangeInputWrap= document.getElementById('pageRangeInputWrap');
const pageRangeInput    = document.getElementById('pageRangeInput');
const pageRangeError    = document.getElementById('pageRangeError');

uploadArea.addEventListener('click', () => fileInput.click());
uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
uploadArea.addEventListener('drop', e => {
    e.preventDefault(); uploadArea.classList.remove('dragover');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleFile(fileInput.files[0]); });

async function handleFile(file) {
    selectedFile = file;
    fileNameEl.textContent = file.name;
    fileSizeEl.textContent = formatSize(file.size);
    fileInfo.classList.add('show');
    splitBtn.classList.add('show');
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
    pageSelector.classList.remove('show');
    pageSelectorMode = 'all';
    pageRangeAll.classList.add('active');
    pageRangeCustom.classList.remove('active');
    pageRangeInputWrap.classList.remove('show');
    pageRangeInput.value = '';
    pageRangeError.classList.remove('show');
    processedQuestions = [];
    _bankSaved = false;

    if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        try {
            if (!pdfjsLib.GlobalWorkerOptions.workerSrc)
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            const ab = await file.arrayBuffer();
            const pdf = await pdfjsLib.getDocument({ data: ab }).promise;
            originalPageCount = pdf.numPages;
            if (originalPageCount > 1) {
                pageTotalEl.textContent = `${originalPageCount} pages total`;
                pageSelector.classList.add('show');
            }
        } catch(e) {}
    }
}

pageRangeAll.addEventListener('click', () => {
    pageSelectorMode = 'all';
    pageRangeAll.classList.add('active');
    pageRangeCustom.classList.remove('active');
    pageRangeInputWrap.classList.remove('show');
});
pageRangeCustom.addEventListener('click', () => {
    pageSelectorMode = 'custom';
    pageRangeCustom.classList.add('active');
    pageRangeAll.classList.remove('active');
    pageRangeInputWrap.classList.add('show');
    pageRangeInput.focus();
});

splitBtn.addEventListener('click', async () => {
    if (!selectedFile) return;
    splitBtn.disabled = true;
    progressCont.classList.add('show');
    progressBar.style.width = '10%';
    progressText.textContent = 'Uploading...';
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');

    let pageRangeParam = '';
    if (pageSelectorMode === 'custom' && originalPageCount > 0) {
        const parsed = parsePageRange(pageRangeInput.value, originalPageCount);
        if (!parsed) {
            pageRangeError.textContent = `Invalid range. Enter numbers between 1 and ${originalPageCount}.`;
            pageRangeError.classList.add('show');
            splitBtn.disabled = false;
            progressCont.classList.remove('show');
            return;
        }
        pageRangeParam = `&pages=${parsed.join(',')}`;
    }

    const savedEmail     = localStorage.getItem('examcrop_email') || '';
    const isReturning    = !!savedEmail;
    const returningParam = isReturning ? `&returning_email=${encodeURIComponent(savedEmail)}` : '';
    const url = `${API_BASE}/api/split?dpi=200&conf_threshold=0.10${pageRangeParam}&is_returning=${isReturning}${returningParam}&source_page=${window.EXAMCROP_SOURCE_PAGE}`;

    try {
        const formData = new FormData();
        formData.append('file', selectedFile);
        progressBar.style.width = '40%';
        progressText.textContent = 'Processing...';

        const res = await fetch(url, { method: 'POST', body: formData });
        if (!res.ok) {
            let err = 'Something went wrong. Please try again.';
            try { const d = await res.json(); err = d.detail || err; } catch(e) {}
            throw new Error(err);
        }

        const uploadId = res.headers.get('X-Upload-Id');
        if (uploadId) window._lastUploadId = uploadId;
        progressBar.style.width = '80%';
        progressText.textContent = 'Rendering...';

        const blob = await res.blob();
        pendingBlob     = blob;
        pendingFilename = selectedFile.name.replace(/\.[^.]+$/, '') + '_questions.pdf';
        processedQuestions  = await extractPages(blob);
        currentQuestionIndex = 0;

        progressBar.style.width = '100%';
        progressCont.classList.remove('show');
        progressBar.style.width = '0%';
        splitBtn.disabled = false;
        showViewer();
    } catch(err) {
        progressCont.classList.remove('show');
        progressBar.style.width = '0%';
        splitBtn.disabled = false;
        errorMsg.textContent = err.message;
        errorMsg.classList.add('show');
    }
});

// ── Viewer ────────────────────────────────────────────────────────────────────

function showViewer() {
    viewerTitle.textContent = 'Questions Preview';
    currentQuestionIndex = 0;
    updateViewerUI();
    viewerOverlay.classList.add('show');
    updateSaveBankBtn();
}

function hideViewer() {
    viewerOverlay.classList.remove('show');
}

function updateViewerUI() {
    if (processedQuestions.length === 0) return;
    viewerImage.src = processedQuestions[currentQuestionIndex].imageUrl || processedQuestions[currentQuestionIndex];
    viewerCounter.textContent = `Question ${currentQuestionIndex + 1} of ${processedQuestions.length}`;
    viewerPrev.disabled = currentQuestionIndex === 0;
    viewerNext.disabled = currentQuestionIndex === processedQuestions.length - 1;
    viewerTrash.classList.remove('hidden');
    downloadAll.textContent = 'Download All (PDF)';
}

function navigateQuestion(dir) {
    const next = currentQuestionIndex + dir;
    if (next >= 0 && next < processedQuestions.length) {
        currentQuestionIndex = next;
        updateViewerUI();
    }
}

viewerClose.addEventListener('click', hideViewer);
viewerPrev.addEventListener('click', () => navigateQuestion(-1));
viewerNext.addEventListener('click', () => navigateQuestion(1));

viewerTrash.addEventListener('click', () => {
    if (processedQuestions.length <= 1) {
        viewerTrash.style.borderColor = 'rgba(220,53,69,0.8)';
        viewerTrash.style.boxShadow   = '0 0 12px rgba(220,53,69,0.5)';
        setTimeout(() => { viewerTrash.style.borderColor = ''; viewerTrash.style.boxShadow = ''; }, 800);
        return;
    }
    processedQuestions.splice(currentQuestionIndex, 1);
    if (currentQuestionIndex >= processedQuestions.length) currentQuestionIndex = processedQuestions.length - 1;
    updateViewerUI();
});

document.addEventListener('keydown', e => {
    if (!viewerOverlay.classList.contains('show')) return;
    if (e.key === 'ArrowLeft')  navigateQuestion(-1);
    if (e.key === 'ArrowRight') navigateQuestion(1);
    if (e.key === 'Escape')     hideViewer();
});

downloadAll.addEventListener('click', () => {
    const saved = localStorage.getItem('examcrop_email');
    if (saved) { submitEmailSilent(saved); buildAndDownload(); }
    else       { hideViewer(); modalOverlay.classList.add('show'); }
});

// ── Save to Bank ──────────────────────────────────────────────────────────────

function updateSaveBankBtn() {
    if (!saveBankBtn) return;
    const loggedIn  = window.Auth && window.Auth.isLoggedIn();
    const hasResult = processedQuestions.length > 0 && window._lastUploadId;
    saveBankBtn.style.display = (loggedIn && hasResult) ? '' : 'none';
}

if (saveBankBtn) {
    saveBankBtn.addEventListener('click', async () => {
        const token    = window.Auth && window.Auth.getToken();
        const uploadId = window._lastUploadId;
        if (!token || !uploadId || _bankSaved) return;

        saveBankBtn.disabled    = true;
        saveBankBtn.textContent = 'Saving...';

        try {
            const res = await fetch(`${API_BASE}/api/save-questions`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ upload_id: uploadId }),
            });

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
        } catch(err) {
            saveBankBtn.textContent = '💾 Save to Bank';
            saveBankBtn.disabled    = false;
        }
    });
}

// ── Email / download ──────────────────────────────────────────────────────────

emailForm.addEventListener('submit', async e => {
    e.preventDefault();
    const email = emailInput.value.trim();
    submitEmailSilent(email);
    localStorage.setItem('examcrop_email', email);
    modalOverlay.classList.remove('show');
    buildAndDownload();
});

async function submitEmailSilent(email) {
    try {
        await fetch(`${API_BASE}/api/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email, comment: '',
                marketing_opt_in: document.getElementById('marketingOptIn')?.checked || false,
                timestamp: new Date().toISOString(),
                upload_id: window._lastUploadId || '',
                is_returning: !!localStorage.getItem('examcrop_email'),
            })
        });
    } catch(e) {}
}

async function buildAndDownload() {
    try {
        if (typeof PDFLib === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js');
        if (typeof JSZip  === 'undefined') await loadScript('https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js');

        const zip = new JSZip();
        await zip.loadAsync(pendingBlob);
        let entry = null;
        zip.forEach((p, e) => { if (p.endsWith('.pdf')) entry = e; });
        if (!entry) throw new Error('no pdf');

        const bytes = new Uint8Array(await (await entry.async('blob')).arrayBuffer());
        const { PDFDocument } = PDFLib;
        const src    = await PDFDocument.load(bytes);
        const out    = await PDFDocument.create();
        const copied = await out.copyPages(src, processedQuestions.map((_, i) => i));
        copied.forEach(p => out.addPage(p));
        const outBytes = await out.save();

        const a = document.createElement('a');
        a.href     = URL.createObjectURL(new Blob([outBytes], { type: 'application/pdf' }));
        a.download = pendingFilename;
        a.click();

        successMsg.textContent = `Downloaded ${processedQuestions.length} questions.`;
        successMsg.classList.add('show');
    } catch(err) {
        errorMsg.textContent = 'Download failed. Please try again.';
        errorMsg.classList.add('show');
    }
}