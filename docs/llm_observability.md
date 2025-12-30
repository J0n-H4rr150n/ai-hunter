# LLM Observability Fields

## Complete Traceability Captured

### Identifiers
- `trace_id` - Unique ID for this LLM call
- `parent_trace_id` - For nested/chained calls
- `session_id` - User session identifier
- `mission_id` - Associated mission

### Model Configuration
- `llm_model` - Model name (e.g., "gemini-2.5-pro")
- `llm_provider` - Provider (google_vertex, openai, anthropic)
- `temperature` - Sampling temperature used
- `top_p` - Nucleus sampling parameter
- `max_tokens` - Token limit

### Input
- `system_prompt` - System instructions
- `user_prompt` - User's input
- `conversation_history` - Prior messages
- `input_tokens` - Token count (input)
- `input_characters` - Character count (input)

### Output
- `llm_response` - Full response text
- `llm_reasoning` - Chain of thought / reasoning
- `llm_decision` - What agent decided to do
- `llm_confidence` - Confidence score (0.0-1.0)
- `output_tokens` - Token count (output)
- `output_characters` - Character count (output)

### Performance
- `timestamp_start` - When call started
- `timestamp_end` - When call completed
- `elapsed_time_ms` - Duration in milliseconds
- `tokens_per_second` - Throughput metric

### Quality & Safety
- `safety_scores` - Per-category safety scores
- `safety_blocked` - Was response blocked?
- `finish_reason` - How generation ended (stop/length/safety)

### Cost & Usage
- `estimated_cost_usd` - Estimated API cost
- `request_id` - Provider's request ID

### Error Handling
- `status` - success/failed/timeout/rate_limited/safety_blocked
- `error_message` - Error details if failed
- `retry_count` - Number of retries
- `fallback_used` - Did we use a fallback model?

### Agent Context
- `agent_name` - Which agent made the call
- `agent_state_before` - Agent's state before call
- `agent_state_after` - Agent's state after call
- `tools_available` - What tools were available
- `tools_called` - Which tools were used
- `memory_retrieved` - RAG/memory context used

### Debugging
- `raw_request` - Complete request payload
- `raw_response` - Complete response payload
- `environment` - development/staging/production

## Usage Example

```python
from core.llm_tracer import LLMTracer, LLMTrace
import uuid

tracer = LLMTracer(database=db, redis_manager=redis_mgr)

# Start trace
trace = await tracer.start_trace(
    trace_id=str(uuid.uuid4()),
    agent_name="TacticalPlanner",
    llm_model="gemini-2.5-pro",
    user_prompt="Generate a security audit plan",
    mission_id=123,
    temperature=0.7
)

# Make LLM call...
response = model.generate_content(prompt)

# End trace
await tracer.end_trace(
    trace,
    llm_response=response.text,
    llm_confidence=0.85,
    llm_decision="execute_scan",
    input_tokens=150,
    output_tokens=300
)
```

## Benefits

1. **Full Audit Trail** - Every LLM decision recorded
2. **Cost Tracking** - Know exactly what you're spending
3. **Performance Monitoring** - Identify slow calls
4. **Quality Assurance** - Track confidence over time
5. **Debugging** - Reproduce exact conditions
6. **Safety Compliance** - Monitor safety violations
7. **A/B Testing** - Compare models/prompts
8. **Alerting** - Trigger on low confidence or errors
