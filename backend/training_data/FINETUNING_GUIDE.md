# FunctionGemma Finetuning Guide

Complete guide for finetuning FunctionGemma (270M) on your custom tools using the Unsloth Colab notebook.

## ✅ Data Validation

Your training data has been validated and is **100% compatible** with the Unsloth notebook!

```
✅ All 334 examples passed validation
✅ Format matches TxT360-3efforts structure
✅ All examples have required "think" field
✅ Tool schemas properly formatted
```

## 📊 Dataset Summary

- **Total Examples**: 334
- **No tool calls**: 30 (greetings, general chat)
- **1 tool call**: 163
- **2 tool calls (parallel)**: 91
- **3 tool calls (parallel)**: 30
- **4 tool calls (parallel)**: 20

## 🚀 Step-by-Step Finetuning

### Step 1: Upload Data

**Option A: Google Drive** (Recommended for Colab)
1. Upload `functiongemma_training.jsonl` to your Google Drive
2. In Colab, mount Drive:
```python
from google.colab import drive
drive.mount('/content/drive')
```

**Option B: Hugging Face**
1. Create account at huggingface.co
2. Upload dataset:
```python
from datasets import load_dataset

dataset = load_dataset("json", data_files="functiongemma_training.jsonl")
dataset.push_to_hub("your-username/functiongemma-tools")
```

### Step 2: Open the Colab Notebook

Navigate to: https://colab.research.google.com/github/unslothai/notebooks/blob/main/nb/FunctionGemma_(270M).ipynb

### Step 3: Modify the Data Loading Cell

Find Cell 19 and replace with:

```python
from datasets import load_dataset, Dataset

# Option A: Load from Google Drive
import json
examples = []
with open('/content/drive/MyDrive/functiongemma_training.jsonl', 'r') as f:
    for line in f:
        examples.append(json.loads(line))
dataset = Dataset.from_list(examples)

# Option B: Load from Hugging Face
# dataset = load_dataset("your-username/functiongemma-tools", split="train")

print(f"Loaded {len(dataset)} examples")
```

### Step 4: Keep the prepare_messages_and_tools Function

**DO NOT MODIFY** Cell 23 - it will automatically:
- Extract tools from system message
- Convert `"think"` field to `<think></think>` tags
- Normalize tool_calls format
- Filter invalid examples

### Step 5: Run Training

The notebook uses these settings (Cell 29):

```python
SFTConfig(
    dataset_text_field = "text",
    per_device_train_batch_size = 4,
    gradient_accumulation_steps = 2,
    warmup_steps = 10,
    max_steps = 500,  # ~1.5 epochs on your 334 examples
    learning_rate = 2e-4,
    optim = "adamw_8bit",
    weight_decay = 0.001,
    lr_scheduler_type = "linear",
)
```

**Recommended Adjustments** for your 334 examples:
- Increase `max_steps` to **1000** for ~3 epochs
- Or use `num_train_epochs = 3` instead of max_steps

### Step 6: Monitor Training

Watch for:
- Loss should decrease steadily
- Expected time: ~15-20 minutes on T4 GPU
- Final loss target: < 0.5

### Step 7: Save the Model

After training completes:

```python
# Save to Hugging Face
model.push_to_hub("your-username/functiongemma-270m-finetuned")
tokenizer.push_to_hub("your-username/functiongemma-270m-finetuned")

# Or save locally
model.save_pretrained("functiongemma-finetuned")
tokenizer.save_pretrained("functiongemma-finetuned")
```

### Step 8: Test the Model

Use Cell 42 to test:

```python
messages = [
    {
        "role": "system",
        "content": "",
    },
    {
        "role": "user",
        "content": "Find information about convoy operations and mark the staging area at 33.5N, 70.2E",
    },
]

text = tokenizer.apply_chat_template(
    messages,
    tools = your_tools,  # Use your 4 tools
    tokenize = False,
    add_generation_prompt = True,
).removeprefix('<bos>')

from transformers import TextStreamer
_ = model.generate(
    **tokenizer(text, return_tensors = "pt").to("cuda"),
    max_new_tokens = 1024,
    streamer = TextStreamer(tokenizer, skip_prompt = False),
    top_p = 0.95, top_k = 64, temperature = 1.0,
)
```

## 📦 Deployment to Railway

### Option 1: vLLM (Recommended)

1. Create `Dockerfile`:
```dockerfile
FROM vllm/vllm-openai:latest

# Copy your finetuned model
COPY ./functiongemma-finetuned /model

# Start vLLM server
CMD ["python", "-m", "vllm.entrypoints.openai.api_server", \
     "--model", "/model", \
     "--port", "8000"]
```

2. Deploy to Railway:
- Connect GitHub repo
- Set environment variables
- Deploy

### Option 2: Ollama

1. Create Modelfile:
```
FROM ./functiongemma-finetuned
```

2. Build and run:
```bash
ollama create functiongemma-custom -f Modelfile
ollama serve
```

### Option 3: Update Existing Railway Deployment

If you already have FunctionGemma on Railway:

1. Replace model files in your deployment
2. Restart the service
3. Update `FUNCTION_API_KEY` in `backend/app/settings.py` if needed

## 🧪 Testing the Finetuned Model

### Test Cases

1. **No tool call** (greeting):
```python
"Hello, how are you?"
# Expected: No tool calls, friendly response
```

2. **Single tool** (search):
```python
"What are the specifications of the M4 carbine?"
# Expected: search_knowledge_base tool call
```

3. **Single tool** (TAK marker):
```python
"Place a marker at checkpoint alpha, coordinates 34.5, -118.2"
# Expected: place_tak_marker tool call with correct params
```

4. **Multiple tools** (parallel):
```python
"Find intel on sector 7 and mark enemy position at 33.5, 70.2"
# Expected: 2 tool calls - search_knowledge_base AND place_tak_marker
```

5. **All tools** (parallel):
```python
"Search for mission brief, mark objective at 35.1, 69.3, create route from base to objective, and alert the team"
# Expected: All 4 tool calls in parallel
```

### Evaluation Metrics

- **Tool Selection Accuracy**: Did it choose the right tool(s)?
- **Parameter Extraction**: Are parameters correct?
- **Parallel Execution**: Does it call multiple tools when needed?
- **No-Tool Detection**: Does it avoid tools for greetings/chat?

## 🔧 Troubleshooting

### Issue: Out of Memory
- Reduce `per_device_train_batch_size` to 2
- Increase `gradient_accumulation_steps` to 4

### Issue: Training Loss Not Decreasing
- Increase `learning_rate` to 3e-4
- Check data format with `validate_format.py`

### Issue: Model Always/Never Calls Tools
- Check if training data is balanced
- Increase training epochs
- Review examples where model fails

### Issue: Incorrect Parameters
- Add more diverse examples for that tool
- Check parameter descriptions in tool schema

## 📈 Expected Results

After finetuning on 334 examples:

- **Greeting Detection**: >95% accuracy (no tools)
- **Single Tool Selection**: >90% accuracy
- **Parameter Extraction**: >85% accuracy
- **Parallel Tool Calls**: >80% accuracy

## 🎯 Next Steps After Finetuning

1. **Collect Real Usage Data**: Log actual queries in production
2. **Iterative Improvement**: Add failed cases to training set
3. **Expand Dataset**: Generate 500-1000 more examples
4. **A/B Testing**: Compare with base FunctionGemma
5. **Monitor Performance**: Track tool call accuracy in production

## 📝 Files Reference

- `functiongemma_training.jsonl` - Main training file (334 examples)
- `tools_schema.json` - Your 4 tool definitions
- `training_examples_readable.json` - Sample examples (first 10)
- `validate_format.py` - Validation script
- `generate_training_data.py` - Data generation script

## 🆘 Need More Data?

To generate more examples:

```bash
cd backend
uv run python scripts/generate_training_data.py
```

Edit the script to:
- Increase `num_examples_per_tool` from 40 to 100
- Add more tool combinations
- Generate domain-specific scenarios

---

**Generated**: February 24, 2026
**Model**: Claude Haiku 4.5 via OpenRouter
**Validation**: ✅ All 334 examples passed
**Notebook**: Unsloth FunctionGemma (270M) Compatible
