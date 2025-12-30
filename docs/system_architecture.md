# **Agentic Security Platform: "Wraith" Architecture Design**

## **1\. Executive Summary**

This document outlines the architecture for an autonomous, agentic AI system designed to solve web security benchmarks (e.g., XBOW) and perform controlled penetration testing tasks.

The system differentiates itself from standard web agents through a **Hybrid Memory Architecture** (Redis for speed, Postgres for wisdom), a **"Triad of Truth"** reconnaissance strategy (Visual \+ Code \+ Network), and a strict **Human-in-the-Loop (HITL) Reinforcement Learning** workflow.

## **2\. High-Level Architecture**

The system follows a **Lambda Architecture** pattern:

* **Hot Path (Real-time):** Redis handles ephemeral state, high-speed telemetry, and UI updates (SSE).  
* **Cold Path (Long-term):** PostgreSQL handles vector embeddings, "Wisdom" storage (RLHF), and finding verification.

graph TD  
    User\[Human Operator\] \<--\>|HITL / Shadow Mode| Interface\[CLI / UI\]  
    Interface \<--\>|Pub/Sub| Redis\[(Redis: Hot State)\]  
      
    subgraph "The Agent Core"  
        Orchestrator\[Main Loop\] \--\>|Direct Control| Browser\[SoMBrowser (Playwright)\]  
        Orchestrator \--\>|Reasoning| Brain\[Vertex AI Agent\]  
        Orchestrator \--\>|Strategy| Planner\[Tactical Planner\]  
    end  
      
    subgraph "Perception Layer"  
        Browser \--\>|Visuals| SoM\[Set of Marks\]  
        Browser \--\>|Traffic| Sniffer\[Network Listener\]  
        Browser \--\>|Code| Source\[DOM & Raw Source\]  
    end  
      
    subgraph "Heavy Weapons"  
        Browser \-.-\>|State Bridge| Fuzzer\[PythonIntruder (httpx)\]  
        Scanner\[TechScanner\] \--\>|Fingerprints| Planner  
    end  
      
    subgraph "Memory & Learning"  
        Brain \<--\>|RAG| PG\[(Postgres \+ pgvector)\]  
        Brain \--\>|Feedback Loop| Redis  
    end  
      
    User \--\>|Ratings/Critiques| PG

## **3\. Core Components**

### **A. The Body: SoMBrowser & TechScanner**

* **Role:** Interaction and Reconnaissance.  
* **Key Innovation: The "Triad of Truth"**  
  1. **Visual:** "Set of Marks" (SoM) Screenshot. Visual grounding prevents "DOM hallucinations" (trying to click hidden elements).  
  2. **Code:** Dynamic DOM \+ Raw Network Response. Essential for finding HTML comments (\<\!-- admin:pass \--\>) invisible to the screenshot.  
  3. **Network:** Passive Network Sniffer (Background thread). Captures JSON API responses silently, enabling data extraction without parsing UI tables.  
* **State Bridge:**  
  * Exports Cookies, LocalStorage, and User-Agent from Playwright.  
  * Hydrates external Python tools (Fuzzer) to allow authenticated attacks outside the browser context.

### **B. The Brain: VertexAgent & TacticalPlanner**

* **Model:** Gemini 1.5 Pro (via Vertex AI).  
* **Planner:**  
  * Runs **once** per phase.  
  * Analyses Recon Data \+ Tech Stack.  
  * Generates a **Budgeted Runbook** (e.g., "1. Fuzz IDOR (3 runs). 2\. Check Admin (5 clicks).").  
* **Executor:**  
  * Runs in a loop.  
  * Consults **Long-Term Memory** (RAG) before every action to avoid past mistakes.

### **C. The Tools: "Heavy Weapons"**

* **PythonIntruder (Fuzzer):**  
  * Async IO (httpx) scanner.  
  * **Usage:** High-volume Enumeration (IDOR ranges).  
  * **Efficiency:** Returns only **Anomalies** (Statistical outliers in content length/status), filtering noise before it hits the LLM.  
  * **Safety:** Hard-coded concurrency limits (5 threads) defined in safety.py.

### **D. The Tracker: Real-Time Telemetry**

* **AgentTracker:**  
  * Broadcasts every thought, action, and network log to Redis Pub/Sub (agent\_live\_events).  
  * Enables a "Flight Recorder" UI where the human can watch the agent "think" in real-time via Server-Sent Events (SSE).

## **4\. Data Architecture**

### **A. Hot Path: Redis**

Used for ephemeral data that needs sub-millisecond access.

| Key Pattern | Type | Purpose | TTL |
| :---- | :---- | :---- | :---- |
| run:{id}:stream | List | Complete event log of the current session. | 1 Hour |
| run:{id}:state | Hash | Current Snapshot (URL, Screenshot ID, Last Action). | 1 Hour |
| agent\_live\_events | Pub/Sub | Real-time broadcast channel for UI. | N/A |
| xbow\_candidates | List | Potential findings waiting for Triage. | Permanent |

### **B. Cold Path: PostgreSQL \+ pgvector**

Used for permanent knowledge and reinforcement learning.

Table: feedback\_memory  
| Column | Type | Purpose |  
| :--- | :--- | :--- |  
| embedding | vector(768) | Semantic vector of the Thought \+ Tool context. |  
| human\_critique | TEXT | The correction provided by the user (e.g., "Don't fuzz \> 100 IDs"). |  
| rating | FLOAT | 0.0 (Bad) to 1.0 (Good). |  
| access\_count | INT | Used for Least-Frequently-Used (LFU) pruning. |  
| timestamp | FLOAT | Used for Time-Decay RAG scoring. |

## **5\. Workflows**

### **Workflow 1: The "Golden Path" (Autonomous)**

1. **Recon:** TechScanner fingerprints stack \-\> Browser captures Triad.  
2. **Planning:** Planner generates Runbook \+ Bids for Budget (e.g., "Need 5 fuzz runs").  
3. **Quotas:** QuotaManager clamps bid against HARD\_CAPS.  
4. **Loop:**  
   * Agent checks Memory (RAG) for warnings.  
   * Agent acts.  
   * QuotaManager decrements counters.  
5. **Pivot:** If stuck/out of budget, Agent requests replan. Loop resets to Step 2\.  
6. **Triage:** Agent reports finding \-\> Analyst Agent verifies \-\> Scorekeeper grades.

### **Workflow 2: The Training Loop (RLHF)**

*Enabled via HITL\_ENABLED \= True*

1. **Pause:** System halts before every action.  
2. **Review:** Human rates proposed action (0.0 \- 1.0) and provides reasoning.  
3. **Storage:**  
   * **Negative Feedback (\<1.0):** Stored as a "Correction" vector.  
   * **Positive Feedback (1.0 \+ Reason):** Stored as a "Reinforcement" vector.  
4. **Learning:** Future runs query this database to self-correct behavior ("I remember the human told me not to do this").

### **Workflow 3: Shadow Mode (Imitation)**

1. **Drive:** User operates the Chrome window manually.  
2. **Spy:** shadow\_copilot.py listens to DOM events via Playwright bridge.  
3. **Capture:**  
   * **Clicks:** Recorded as positive training examples (Rating 1.0).  
   * **Highlights:** Sent to FindingsAnalyst for immediate verification (Secret scanning).  
4. **Result:** Effortless creation of "Golden Path" training data.

## **6\. Safety & Guardrails**

The system implements the **"Contractor Pattern"** for safety. The Agent is a contractor who must request resources.

1. **safety.py:**  
   * **Hard Limits:** Absolute ceilings (e.g., FUZZER\_MAX\_RANGE \= 50). The LLM physically cannot request more.  
   * **Sanitization:** Input clamping (e.g., truncate\_context limits DOM size to 20k chars to prevent token overflow).  
2. **QuotaManager:**  
   * **Budgeting:** Tracks usage per phase.  
   * **Feedback:** If Agent hits a limit (run\_intruder used 3/3 times), it receives a QUOTA EXCEEDED error, forcing it to rethink or replan.  
3. **Token Efficiency:**  
   * **RAG Pruning:** Only injects top-3 relevant memories.  
   * **Network Filtering:** Sniffer discards images/CSS/Fonts, keeping only JSON/HTML.