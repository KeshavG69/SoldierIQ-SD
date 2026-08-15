# Testing FunctionGemma Finetuned Model

Guide for testing your finetuned FunctionGemma model locally with Ollama.

## ✅ What Was Updated

### 1. Added Ollama Provider Support
- Updated `clients/ultimate_llm.py` to support local Ollama
- Base URL: `http://localhost:11434/v1`

### 2. Updated Chat Service
- Modified `services/chat.py` to use your finetuned model
- Model: `hf.co/Keshav069/functiongemma_finetune_gguf:latest`
- Hybrid mode: FunctionGemma (tool calling) + Gemma 3 4B (output)

### 3. Created Test Scripts
- `test_functiongemma.py` - Full agent testing with tool execution
- `test_functiongemma_simple.py` - Quick model response testing

## 🚀 Setup

### Step 1: Make Your HuggingFace Model Public

Go to https://huggingface.co/Keshav069/functiongemma_finetune_gguf/settings and make it public.

### Step 2: Start Ollama

```bash
# Make sure Ollama is running
ollama serve
```

### Step 3: Pull Your Model in Ollama

```bash
# Pull your finetuned model
ollama pull hf.co/Keshav069/functiongemma_finetune_gguf:latest

# Verify it's available
ollama list
```

## 🧪 Running Tests

### Option 1: Simple Test (Quick Validation)

Tests direct model responses without full agent setup:

```bash
cd backend
uv run python test_functiongemma_simple.py
```

**What it tests:**
- Basic responses
- Tool call generation
- Parameter extraction

**Expected output:**
```
Query: Hello!
Response: Hello! How can I help you today?

Query: Find information about convoy operations
Response: <think>User wants to search knowledge base...</think>
Tool: search_knowledge_base(query="convoy operations")
```

### Option 2: Full Agent Test (Complete Workflow)

Tests the full hybrid agent with tool execution and streaming:

```bash
cd backend
uv run python test_functiongemma.py
```

**What it tests:**
- 10 comprehensive test cases
- No tool calls (greetings)
- Single tool calls (all 4 tools)
- Multiple parallel tool calls
- All 4 tools in parallel

**Expected output:**
```
TEST: Single Tool - Search Knowledge Base
Query: Find information about convoy operations procedures
Expected: search_knowledge_base tool call
--------------------------------------------------------------------------------
🔧 Tool Called: search_knowledge_base
   Arguments: {"query": "convoy operations procedures"}
📝 Response: Based on the knowledge base...
--------------------------------------------------------------------------------
✅ Tools Called: search_knowledge_base
```

## 📊 Test Cases Covered

### 1. No Tool Calls
- ✅ Greetings: "Hello!"
- ✅ General questions: "What can you help me with?"

### 2. Single Tool Calls
- ✅ **search_knowledge_base**: "Find convoy operations procedures"
- ✅ **place_tak_marker**: "Place marker at 34.5N, 118.2W"
- ✅ **send_tak_message**: "Broadcast patrol commencing"
- ✅ **create_tak_route**: "Create route from base to checkpoint"

### 3. Multiple Tools (Parallel)
- ✅ **2 tools**: "Find intel and mark position"
- ✅ **3 tools**: "Search, mark, and alert team"
- ✅ **4 tools**: "Search, mark, route, broadcast"

## 🔍 What to Look For

### Success Indicators ✅
1. **Greetings** → No tool calls
2. **Single tool queries** → Correct tool selected
3. **Parameters** → Correctly extracted from query
4. **Multiple tools** → All tools called in parallel
5. **Output** → Clear, natural language response

### Failure Indicators ❌
1. **Wrong tool** selected
2. **Missing parameters** or incorrect values
3. **No tool calls** when tools are needed
4. **Sequential** instead of parallel tool calls
5. **Hallucinated** tool names or parameters

## 🐛 Troubleshooting

### Issue: "Connection refused" or Ollama not found

**Solution:**
```bash
# Start Ollama server
ollama serve

# In another terminal, verify it's running
curl http://localhost:11434/v1/models
```

### Issue: Model not found

**Solution:**
```bash
# Make HuggingFace repo public first
# Then pull the model
ollama pull hf.co/Keshav069/functiongemma_finetune_gguf:latest

# Check if downloaded
ollama list
```

### Issue: Slow responses

**Explanation:** GGUF models run on CPU by default. This is expected for local testing.

**Options:**
- Use smaller quantization (Q4_K_M instead of Q8)
- Reduce context length
- Use GPU-accelerated Ollama build

### Issue: Tool calls not working

**Check:**
1. Model was trained on correct format (TxT360-3efforts)
2. Training completed successfully
3. Model quantization didn't break tool calling

**Debug:**
```bash
# Test with simple query
ollama run hf.co/Keshav069/functiongemma_finetune_gguf:latest "Find convoy procedures"

# Check if it generates tool calls
```

## 📈 Performance Benchmarks

### Expected Performance (Local Ollama on M1/M2 Mac)
- **Greeting response**: ~2-3 seconds
- **Single tool call**: ~3-5 seconds
- **Multiple tool calls**: ~5-8 seconds
- **Full conversation**: ~10-15 seconds

### Comparison
- **Local Ollama**: Slower but free, private
- **Railway hosted**: Faster, always available, costs $
- **OpenRouter models**: Much faster, costs $$

## 🚀 Next Steps After Testing

### If Tests Pass ✅
1. **Use in development**: Keep using local Ollama for testing
2. **Deploy to Railway**: For production, deploy GGUF to Railway
3. **Monitor performance**: Track tool calling accuracy
4. **Collect data**: Log failed cases for future training

### If Tests Fail ❌
1. **Review training data**: Check `training_data/functiongemma_training.jsonl`
2. **Add more examples**: Generate more training data
3. **Retrain**: Run Colab notebook again with updated data
4. **Test iteratively**: Test → Train → Test cycle

## 📝 Manual Testing

You can also test manually:

```bash
# Start interactive session
ollama run hf.co/Keshav069/functiongemma_finetune_gguf:latest

# Try queries
>>> Hello!
>>> Find information about convoy operations
>>> Place a marker at 34.5N, 118.2W
>>> Search for intel and mark position at 33.5, 70.2
```

## 🔄 Switching Between Models

### Use Local Ollama (Current Setup)
Already configured! Just run the tests.

### Switch Back to Railway
Edit `services/chat.py` line 47:
```python
# Change this:
primary_llm = get_llm_agno(model="hf.co/Keshav069/functiongemma_finetune_gguf:latest", provider="ollama")

# To this:
primary_llm = get_llm_agno(model="functiongemma:270m", provider="functiongemma")
```

### Use Different Model
Edit `services/chat.py` line 47:
```python
primary_llm = get_llm_agno(model="your-model-name", provider="ollama")
```

## 📊 Logging and Debugging

Check logs for detailed info:
```bash
# Logs show:
# - Model initialization
# - Tool calls made
# - Parameters extracted
# - Response generation

# View logs in real-time
tail -f logs/app.log
```

---

**Model**: `hf.co/Keshav069/functiongemma_finetune_gguf:latest`
**Provider**: Ollama (local)
**Hybrid Mode**: FunctionGemma + Gemma 3 4B
**Training Data**: 334 examples covering 0-4 tool calls
