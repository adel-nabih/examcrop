#!/usr/bin/env python3
"""
YOLOv26-Based Question Splitter - HEAVILY OPTIMIZED
Key Improvements:
1. Parallel processing of PDF pages
2. Direct PDF cropping without unnecessary image conversions
3. Batch YOLO inference
4. Efficient memory management
5. Reduced I/O operations
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple
import fitz
from PIL import Image
import cv2
import numpy as np
import pandas as pd
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("ERROR: ultralytics not installed. Run: pip install ultralytics")


class YOLOQuestionSplitter:
    """YOLOv11-based worksheet question splitter - heavily optimized"""
    
    def __init__(self, debug: bool = False, model_path: str = None):
        self.debug = debug
        self.model_path = model_path or 'best.pt'
        
        if not YOLO_AVAILABLE:
            raise ImportError("ultralytics not available")
        
        if os.path.exists(self.model_path):
            if self.debug:
                print(f"Loading model: {self.model_path}")
            self.model = YOLO(self.model_path)
            self.use_custom_model = True
        else:
            raise FileNotFoundError(f"Model not found: {self.model_path}")
    
    def convert_to_pdf(self, input_path: str) -> str:
        """Convert image to PDF if needed"""
        file_ext = Path(input_path).suffix.lower()
        if file_ext == '.pdf':
            return input_path
        
        img = Image.open(input_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        temp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        temp_pdf_path = temp_pdf.name
        temp_pdf.close()
        
        img.save(temp_pdf_path, "PDF", resolution=300.0, quality=95)
        return temp_pdf_path
    
    def render_page_to_image(self, page: fitz.Page, zoom: float) -> np.ndarray:
        """Render a single page to numpy array - optimized"""
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        img_data = pix.samples
        img = np.frombuffer(img_data, dtype=np.uint8)
        img = img.reshape(pix.height, pix.width, pix.n)
        
        if pix.n == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        elif pix.n == 4:
            img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        
        return img
    
    def pdf_to_images_parallel(self, pdf_path: str, dpi: int = 200) -> List[Dict]:
        """Convert PDF pages to images in parallel - MAJOR SPEEDUP"""
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        zoom = dpi / 72
        
        def process_page(page_num: int) -> Dict:
            page = doc[page_num]
            img = self.render_page_to_image(page, zoom)
            return {
                'page_num': page_num,
                'image': img,
                'width': img.shape[1],
                'height': img.shape[0]
            }
        
        page_data = []
        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = [executor.submit(process_page, i) for i in range(page_count)]
            for future in as_completed(futures):
                page_data.append(future.result())
        
        doc.close()
        
        page_data.sort(key=lambda x: x['page_num'])
        return page_data
    
    def detect_questions_batch(self, images: List[np.ndarray], conf_threshold: float = 0.05) -> List[List[Dict]]:
        """Batch YOLO inference for multiple images - MAJOR SPEEDUP"""
        results = self.model(images, conf=conf_threshold, imgsz=1024, verbose=False)
        
        all_blocks = []
        for result in results:
            blocks = []
            if result.boxes is not None and len(result.boxes) > 0:
                boxes = result.boxes.xyxy.cpu().numpy()
                confidences = result.boxes.conf.cpu().numpy()
                classes = result.boxes.cls.cpu().numpy()
                
                for box, conf, cls in zip(boxes, confidences, classes):
                    if cls != 0:
                        continue
                    x1, y1, x2, y2 = box
                    
                    blocks.append({
                        'x': int(x1),
                        'y': int(y1),
                        'w': int(x2 - x1),
                        'h': int(y2 - y1),
                        'confidence': float(conf)
                    })
                    print(f"conf: {conf:.3f}  xyxy: {box.tolist()}")
            all_blocks.append(blocks)
        
        return all_blocks
    
    def apply_nms(self, blocks: List[Dict], iou_threshold: float = 0.85) -> List[Dict]:
        """Non-Maximum Suppression to remove duplicates"""
        if len(blocks) == 0:
            return []
        
        def calc_iou(box1, box2):
            x1 = max(box1['x'], box2['x'])
            y1 = max(box1['y'], box2['y'])
            x2 = min(box1['x'] + box1['w'], box2['x'] + box2['w'])
            y2 = min(box1['y'] + box1['h'], box2['y'] + box2['h'])
            
            if x2 < x1 or y2 < y1:
                return 0.0
            
            intersection = (x2 - x1) * (y2 - y1)
            area1 = box1['w'] * box1['h']
            area2 = box2['w'] * box2['h']
            union = area1 + area2 - intersection
            
            return intersection / union if union > 0 else 0
        
        unique_blocks = []
        sorted_by_conf = sorted(blocks, key=lambda b: b['confidence'], reverse=True)
        
        for block in sorted_by_conf:
            is_duplicate = False
            for unique in unique_blocks:
                if calc_iou(block, unique) > iou_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_blocks.append(block)
        
        return unique_blocks
    
    def assign_question_numbers(self, blocks: List[Dict], page_offset: int = 0) -> pd.DataFrame:
        """Assign question numbers by position"""
        if len(blocks) == 0:
            return pd.DataFrame()
        
        unique_blocks = self.apply_nms(blocks)
        
        def sort_key(b):
            row = round(b['y'] / 50)
            return (row, b['x'])
        
        sorted_blocks = sorted(unique_blocks, key=sort_key)
        
        questions = []
        for i, block in enumerate(sorted_blocks):
            questions.append({
                'question_num': page_offset + i + 1,
                'x': block['x'],
                'y': block['y'],
                'w': block['w'],
                'h': block['h'],
                'confidence': block['confidence']
            })
        
        return pd.DataFrame(questions)
    
    def crop_questions_from_pdf(self, pdf_doc: fitz.Document, questions_df: pd.DataFrame,
                               page_num: int, dpi: int, output_dir: str) -> List[Dict]:
        """Crop questions directly from PDF without intermediate conversions - MAJOR SPEEDUP.
        Returns list of {q_num, page_num, rect} for thumbnail generation."""
        page = pdf_doc[page_num]
        rotation = page.rotation

        if rotation != 0:
        # Apply rotation to the transformation matrix instead of stripping metadata
            page.set_rotation(0)
        
        scale = 72 / dpi
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        original_rect = page.rect
        margin = 5
        crop_info = []
        
        for _, row in questions_df.iterrows():
            q_num = int(row['question_num'])
            
            x_pts = max(0, row['x'] * scale - margin)
            y_pts = max(0, row['y'] * scale - margin)
            w_pts = row['w'] * scale + 2 * margin
            h_pts = row['h'] * scale + 2 * margin
            
            x2_pts = min(original_rect.width, x_pts + w_pts)
            y2_pts = min(original_rect.height, y_pts + h_pts)
            
            rect = fitz.Rect(x_pts, y_pts, x2_pts, y2_pts)
            
            out_pdf = fitz.open()
            out_page = out_pdf.new_page(width=rect.width, height=rect.height)
            out_page.show_pdf_page(out_page.rect, pdf_doc, page_num, clip=rect)
            out_page.set_rotation(0)
            
            filepath = Path(output_dir) / f"question_{q_num:02d}.pdf"
            out_pdf.save(filepath, garbage=4, deflate=True, clean=True, pretty=False)
            out_pdf.close()

            crop_info.append({'q_num': q_num, 'page_num': page_num, 'rect': rect})

        return crop_info
    
    def render_question_thumbnail(self, pdf_doc: fitz.Document, page_num: int,
                                   rect: fitz.Rect, jpeg_quality: int = 85) -> bytes:
        """
        Render a question crop rect from a PDF page to JPEG bytes.
        Used by main.py during background R2 upload to generate thumbnails.
        Returns raw JPEG bytes, or raises on failure.
        """
        zoom = 2.0  # 144 dpi — crisp enough for bank thumbnails, small file size
        mat = fitz.Matrix(zoom, zoom)
        page = pdf_doc[page_num]
        clip = fitz.Rect(rect)  # copy — avoid mutating caller's rect
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 3:
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        else:
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGBA2BGR)
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        success, buf = cv2.imencode('.jpg', img_bgr, encode_params)
        if not success:
            raise RuntimeError(f"JPEG encoding failed for page {page_num} rect {rect}")
        return buf.tobytes()

    def visualize(self, image: np.ndarray, df: pd.DataFrame, output_path: str):
        """Save visualization of detected questions"""
        vis = image.copy()
        for _, row in df.iterrows():
            x, y, w, h = int(row['x']), int(row['y']), int(row['w']), int(row['h'])
            q = int(row['question_num'])
            conf = row['confidence']
            
            cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 255, 0), 3)
            label = f"Q{q} ({conf:.2f})"
            cv2.putText(vis, label, (x+5, y+30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        cv2.imwrite(output_path, vis)
    
    def split_worksheet(self, input_path: str, output_dir: str,
                       dpi: int = 200, cleanup_temp: bool = True,
                       conf_threshold: float = 0.1) -> List[Dict]:
        """
        Main pipeline - HEAVILY OPTIMIZED

        Key optimizations:
        1. Parallel page rendering
        2. Batch YOLO inference
        3. Direct PDF cropping (no intermediate image files)
        4. Reduced I/O operations

        Returns list of {q_num, page_num, rect} for each detected question,
        used by main.py to generate JPEG thumbnails during background R2 upload.
        """
        temp_pdf = None
        pdf_path = self.convert_to_pdf(input_path)
        if pdf_path != input_path:
            temp_pdf = pdf_path
        
        try:
            page_data_list = self.pdf_to_images_parallel(pdf_path, dpi)
            
            images = [page_data['image'] for page_data in page_data_list]
            all_blocks = self.detect_questions_batch(images, conf_threshold)
            
            all_questions_found = False
            total_questions = 0
            question_offset = 0
            all_crop_info: List[Dict] = []
            
            pdf_doc = fitz.open(pdf_path)

            # Normalize all page rotations
            for i in range(len(pdf_doc)):
                page = pdf_doc[i]
                if page.rotation != 0:
                    page.set_rotation(0)

            normalized_path = pdf_path + "_normalized.pdf"
            pdf_doc.save(normalized_path)
            pdf_doc.close()
            pdf_doc = fitz.open(normalized_path)
            
            for page_num, (page_data, blocks) in enumerate(zip(page_data_list, all_blocks)):
                if not blocks:
                    continue
                
                df = self.assign_question_numbers(blocks, question_offset)
                
                if len(df) == 0:
                    continue
                
                all_questions_found = True
                total_questions += len(df)
                question_offset = df['question_num'].max()
                
                if self.debug:
                    debug_path = f"debug_yolo_page_{page_num+1}.png"
                    self.visualize(page_data['image'], df, debug_path)
                
                page_crop_info = self.crop_questions_from_pdf(pdf_doc, df, page_num, dpi, output_dir)
                all_crop_info.extend(page_crop_info)
            
            pdf_doc.close()
            
            if not all_questions_found:
                sys.exit(1)

            return all_crop_info
        
        finally:
            if temp_pdf and cleanup_temp and os.path.exists(temp_pdf):
                os.unlink(temp_pdf)
            if os.path.exists(normalized_path):
                os.unlink(normalized_path)


def main():
    if len(sys.argv) < 3:
        print("Usage: python split_pdf <input> <output_dir> [--debug] [--model path] [--conf 0.1] [--dpi 200]")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_dir = sys.argv[2]
    
    model_path = 'best.pt'
    conf_threshold = 0.15
    dpi = 200
    debug = '--debug' in sys.argv
    
    if '--model' in sys.argv:
        idx = sys.argv.index('--model')
        if idx + 1 < len(sys.argv):
            model_path = sys.argv[idx + 1]
    
    if '--conf' in sys.argv:
        idx = sys.argv.index('--conf')
        if idx + 1 < len(sys.argv):
            conf_threshold = float(sys.argv[idx + 1])
    
    if '--dpi' in sys.argv:
        idx = sys.argv.index('--dpi')
        if idx + 1 < len(sys.argv):
            dpi = int(sys.argv[idx + 1])
    
    splitter = YOLOQuestionSplitter(debug=debug, model_path=model_path)
    splitter.split_worksheet(input_path, output_dir, dpi=dpi, conf_threshold=conf_threshold)


if __name__ == "__main__":
    main()