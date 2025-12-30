# Iteration System Integration for AutonomousLoop
# This document describes the changes needed to integrate iterations into autonomous_loop.py

## Core Changes Required:

### 1. Update start_mission() - Line 107
- After plan approval, instead of calling run_loop() immediately
- Create Iteration 1 in database
- Call run_iteration(iteration_id) instead

### 2. Add run_iteration(iteration_id) method
- Load iteration from database 
- Execute plan steps for that iteration only
- Track progress
- When complete, call summarize_iteration()
- Publish iteration_completed event with summary
- Wait for user decision on next iteration

### 3. Add summarize_iteration_findings(iteration_id) method
- Aggregate findings since iteration started
- Generate summary using LLM
- Save to database
- Return summary text

### 4. Add generate_next_iteration_plan(mission_id, previous_summaries) method
- Load all previous iteration summaries
- Generate new plan based on findings
- Focus on unexplored areas
- Create new iteration in database
- Return iteration_id

### 5. Backend changes needed in main.py:
- approve_plan should create Iteration 1
- approve_replan should call generate_next_iteration_plan
- run_mission should support iteration execution

This is a comprehensive refactoring. Let me know if you want me to proceed.
