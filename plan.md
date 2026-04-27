# Temporal-Backed Chatbot (Similar to ChatGPT)
This project contains the code for a ChatGPT replica using Temporal on the backend to orchestrate the chat sessions between the LLM and the user.

## Coding patterns to follow
* Keep things simple when possible. Prioritize simplicity and brevity over cleverness
* Avoid overloading single files with too much code. Architect the codebase well so that it's easy to maintain and read through
* Create commit to git often. Keep commits organized. Follow conventional commits
* Keep track of your progress using this file. Use the running list of requirements. Create a todo list in this file and use it to track progress.

## Running list of requirements (update this as necessary)
* Must have a unique UX
* Must be build using flutter for the front end and python for the back end
* Must be dockerized and setup for a kubernetes deployment
* Must rely on Temporal. The backend should be a Temporal worker
* Must use environment variables for configuration options
* Must pass all data required for workflow execution into the workflow as input
* Must support a local Temporal instance (docker compose) as well as an external temporal instance (configurable)
* Must support a local postgres instance (jsonb where possible) as well as an external postgres instanced (configurable)

## Progress

### ✅ Done
- [x] Backend: Fixed Pydantic v2 frozen model settings mutation (uses override dict now)
- [x] Backend: Fixed chat endpoint to support existing thread_id (not just creating new threads)
- [x] Backend: Fixed execute_workflow usage (returns result directly, no .result() call)
- [x] Backend: Fixed Temporal sandbox issue — moved settings/DB imports inside activity bodies
- [x] Backend: Fixed metadata_ column mapping in CRUD (was using wrong attribute name)
- [x] Backend: Fixed rename endpoint to accept JSON body instead of query param
- [x] Backend: Added unique workflow IDs to prevent collisions
- [x] Backend: Added LLM config passthrough from request → workflow → activity
- [x] Frontend: Complete UI redesign — ChatGPT-style layout with sidebar + chat area
- [x] Frontend: Premium dark theme with violet accent, Google Fonts, animations
- [x] Frontend: Optimistic message sending (user message appears immediately)
- [x] Frontend: Animated typing indicator while waiting for LLM response
- [x] Frontend: Date-grouped thread list (Today/Yesterday/Previous 7 Days/Older)
- [x] Frontend: Suggestion chips on welcome screen
- [x] Frontend: Responsive layout (sidebar on desktop, drawer on mobile)
- [x] Frontend: Removed broken provider pattern, cleaned up duplicate files
- [x] Docker: Added healthchecks and restart policies for startup race conditions
- [x] Flutter analyze: 0 issues

### 🔲 To Do
- [ ] End-to-end test: send a chat message with Ollama running
- [ ] Add streaming support (SSE) for real-time token display
- [ ] K8s manifests may need updating for new architecture
