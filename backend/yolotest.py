from ultralytics import YOLO

# Load your current model
model = YOLO('best.pt')

# Check model architecture
print(f"Model type: {model.model}")
print(f"Model task: {model.task}")

# This will tell you if it's YOLOv11 or YOLO26
info = model.info()
print(info)