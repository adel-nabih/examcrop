#!/usr/bin/env python3
"""
YOLOv26-Based Question Splitter - OPTIMIZED FOR SPEED
- Removed OCR (not needed)
- Reduced logging
- Optimized image processing
"""

import os
import sys
from pathlib import Path
from typing import List, Dict
import fitz
from PIL import Image
import cv2
import numpy as np
import pandas as pd
import tempfile

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    print("ERROR: ultralytics not installed. Run: pip install ultralytics")


class YOLOQuestionSplitter:
    """YOLOv26-based worksheet question splitter - optimized version"""
    
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
    
    def pdf_to_images(self, pdf_path: str, dpi: int = 200) -> List[Dict]:
        """Convert PDF pages to OpenCV images - optimized"""
        doc = fitz.open(pdf_path)
        page_data = []
        
        zoom = dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Render page to image
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert to numpy array
            img_data = pix.samples
            img = np.frombuffer(img_data, dtype=np.uint8)
            img = img.reshape(pix.height, pix.width, pix.n)
            
            # Convert color space
            if pix.n == 3:
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif pix.n == 4:
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            
            page_data.append({
                'image': img,
                'width': pix.width,
                'height': pix.height
            })
        
        doc.close()
        return page_data
    
    def detect_questions_with_yolo(self, image: np.ndarray, conf_threshold: float = 0.1) -> List[Dict]:
        """Use YOLO model to detect question blocks - optimized"""
        # Run inference (verbose=False to reduce overhead)
        results = self.model(image, conf=conf_threshold, verbose=False)
        
        blocks = []
        if len(results) > 0:
            result = results[0]
            
            if result.boxes is not None and len(result.boxes) > 0:
                boxes = result.boxes.xyxy.cpu().numpy()
                confidences = result.boxes.conf.cpu().numpy()
                classes = result.boxes.cls.cpu().numpy()
                
                for box, conf, cls in zip(boxes, confidences, classes):
                    if cls != 0:  # class 0 is 'question'
                        continue
                    x1, y1, x2, y2 = box
                    
                    blocks.append({
                        'x': int(x1),
                        'y': int(y1),
                        'w': int(x2 - x1),
                        'h': int(y2 - y1),
                        'confidence': float(conf)
                    })
        
        return blocks
    
    def assign_question_numbers(self, blocks: List[Dict], page_offset: int = 0) -> pd.DataFrame:
        """Assign question numbers by position - optimized (no OCR)"""
        if len(blocks) == 0:
            return pd.DataFrame()
        
        # Remove duplicates using NMS
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
        
        # NMS: keep highest confidence boxes
        unique_blocks = []
        sorted_by_conf = sorted(blocks, key=lambda b: b['confidence'], reverse=True)
        
        for block in sorted_by_conf:
            is_duplicate = False
            for unique in unique_blocks:
                if calc_iou(block, unique) > 0.5:
                    is_duplicate = True
                    break
            if not is_duplicate:
                unique_blocks.append(block)
        
        # Sort by position: top to bottom, left to right
        def sort_key(b):
            row = round(b['y'] / 50)
            return (row, b['x'])
        
        sorted_blocks = sorted(unique_blocks, key=sort_key)
        
        # Assign sequential numbers
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
    
    def crop_from_pdf(self, pdf_path: str, df: pd.DataFrame, page_num: int, 
                     dpi: int, output_dir: str):
        """Crop questions from PDF - optimized"""
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        
        if page.rotation != 0:
            page.set_rotation(0)
        
        scale = 72 / dpi
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        original_rect = page.rect
        margin = 5
        
        for _, row in df.iterrows():
            q_num = int(row['question_num'])
            
            # Convert pixel coordinates to PDF points
            x_pts = max(0, row['x'] * scale - margin)
            y_pts = max(0, row['y'] * scale - margin)
            w_pts = row['w'] * scale + 2 * margin
            h_pts = row['h'] * scale + 2 * margin
            
            # Bounds check
            x2_pts = min(original_rect.width, x_pts + w_pts)
            y2_pts = min(original_rect.height, y_pts + h_pts)
            
            rect = fitz.Rect(x_pts, y_pts, x2_pts, y2_pts)
            
            # Create cropped PDF
            out_pdf = fitz.open()
            out_page = out_pdf.new_page(width=rect.width, height=rect.height)
            out_page.show_pdf_page(out_page.rect, doc, page_num, clip=rect)
            out_page.set_rotation(0)
            
            filepath = Path(output_dir) / f"question_{q_num:02d}.pdf"
            out_pdf.save(filepath, garbage=4, deflate=True, clean=True, pretty=False)
            out_pdf.close()
        
        doc.close()
    
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
                       conf_threshold: float = 0.1):
        """
        Main pipeline - OPTIMIZED FOR SPEED
        """
        temp_pdf = None
        pdf_path = self.convert_to_pdf(input_path)
        if pdf_path != input_path:
            temp_pdf = pdf_path
        
        try:
            # Convert pages to images
            page_data_list = self.pdf_to_images(pdf_path, dpi)
            
            all_questions_found = False
            total_questions = 0
            question_offset = 0
            
            for page_num, page_data in enumerate(page_data_list):
                image = page_data['image']
                
                # Detect questions
                blocks = self.detect_questions_with_yolo(image, conf_threshold)
                
                if not blocks:
                    continue
                
                # Assign numbers
                df = self.assign_question_numbers(blocks, question_offset)
                
                if len(df) == 0:
                    continue
                
                all_questions_found = True
                total_questions += len(df)
                question_offset = df['question_num'].max()
                
                # Save visualization if debug
                if self.debug:
                    debug_path = f"debug_yolo_page_{page_num+1}.png"
                    self.visualize(image, df, debug_path)
                
                # Crop and save
                self.crop_from_pdf(pdf_path, df, page_num, dpi, output_dir)
            
            if not all_questions_found:
                sys.exit(1)
        
        finally:
            if temp_pdf and cleanup_temp and os.path.exists(temp_pdf):
                os.unlink(temp_pdf)


def main():
    if len(sys.argv) < 3:
        print("Usage: python split_pdf.py <input> <output_dir> [--debug] [--model path] [--conf 0.1] [--dpi 200]")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_dir = sys.argv[2]
    
    model_path = 'best.pt'
    conf_threshold = 0.1
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