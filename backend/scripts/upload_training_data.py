# /// script
# dependencies = ["datasets", "huggingface_hub"]
# ///
from datasets import Dataset
from huggingface_hub import login
import json
import os

# Login
token = os.environ.get('HF_TOKEN')
if token:
    login(token=token)
    print('✅ Logged in to HuggingFace')
else:
    print('❌ HF_TOKEN not set')
    exit(1)

# Load training data
data = []
with open('training_data/functiongemma_training.jsonl') as f:
    for line in f:
        data.append(json.loads(line))

print(f'Loaded {len(data)} training examples')

# Create dataset
dataset = Dataset.from_list(data)
print(f'Dataset has {len(dataset)} rows')

# Push to Hub
print('Pushing to HuggingFace Hub...')
dataset.push_to_hub('Keshav069/functiongemma_training_data', private=False)
print('✅ Dataset uploaded successfully!')
print('View at: https://huggingface.co/datasets/Keshav069/functiongemma_training_data')
