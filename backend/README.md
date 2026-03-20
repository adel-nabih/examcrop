# ExamCrop

AI-powered tool that splits exam papers and worksheets into individual questions as separate PDFs. Uses a custom-trained YOLO26 model for visual question boundary detection — no text parsing.

## Stack

- **Backend** — FastAPI (Railway)
- **Model** — YOLO26s, custom trained
- **Storage** — Cloudflare R2
- **Database/Auth** — PocketBase (Railway)
- **Frontend** — Vanilla JS, served by FastAPI

## Project Structure

```
ExamCrop/
├── backend/
│   ├── main.py          # FastAPI app, endpoints, R2, PocketBase
│   ├── split_pdf.py     # YOLO inference pipeline
│   ├── best.pt          # Model weights (not committed)
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── script.js
│   ├── styles.css
│   ├── bank.html        # Question bank UI
│   ├── auth.js
│   └── pricing.html
└── training/
    ├── dataset.yaml
    ├── train/
    │   ├── images/
    │   └── labels/
    └── val/
        ├── images/
        └── labels/
```

## Local Development

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

Requires a `.env` file inside `backend/` with:

```
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
POCKETBASE_EMAIL=
POCKETBASE_PASSWORD=
```

## Training

Training runs on Google Colab. To retrain:

1. Annotate pages using [makesense.ai](https://makesense.ai) — one class: `question`
2. Place images in `training/train/images/` and labels in `training/train/labels/`
3. Zip the training folder with current weights:
```bash
zip -r training_package.zip training/ backend/best.pt
```
4. Upload to Google Drive and run the Colab notebook

## Supported Formats

PDF, JPG, PNG, HEIC — max 20MB, max 20 pages

## Curricula

IGCSE, Edexcel, SAT, IB, Thanaweya Amma