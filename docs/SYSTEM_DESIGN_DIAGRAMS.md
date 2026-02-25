# TTH System Design Diagrams (Overview to Detailed Components)

This document visualizes the full system design for both:
1. Hybrid mode (`api` + `self_host` mix).
2. API-only mode (run locally on MacBook, no local model serving).

Diagram depth:
1. Section 0: lean v1 single-service baseline (primary implementation target).
2. Sections 1 to 11: system overview and end-to-end behavior.
3. Sections 12 to 21: detailed component design before implementation.

## 0) Lean v1 Single-Service Topology (Primary)
```mermaid
flowchart LR
  client["Client"]

  subgraph backend["FastAPI Service (Single Process in v1)"]
    gw["Gateway Routes (HTTP + WS)"]
    auth["Auth + Rate Limit"]
    orch["Orchestrator Engine"]
    ctrl["Control Mapper"]
    route["Adapter Registry + Router"]
    drift["Drift Controller"]
    sess["In-Memory Session Store"]
    obs["Logging + Metrics + Traces"]
  end

  subgraph providers["External APIs (API-only mode)"]
    llm["LLM API"]
    tts["TTS API"]
    avatar["Avatar API"]
  end

  client --> gw --> auth --> orch
  orch --> ctrl
  orch --> route
  orch --> drift
  orch --> sess
  route --> llm
  route --> tts
  route --> avatar
  gw --> obs
  orch --> obs
```

## 1) High-Level Architecture (Hybrid + API-only Compatible)
```mermaid
flowchart LR
  client["Client App (Web/Mobile/Desktop)"]
  gateway["API Gateway (HTTP + WebSocket)"]
  auth["Auth + Rate Limit"]
  orchestrator["Realtime Orchestrator"]
  session["Session Manager"]
  control["Control Plane"]
  align["Alignment + Drift Controller"]
  mux["A/V Mux + Stream Packager"]
  obs["Observability (Logs/Traces/Metrics)"]

  subgraph routing["Provider Routing Layer"]
    router["Provider Router"]
    fb["Fallback Policy"]
    health["Health Registry"]
  end

  subgraph llm_layer["LLM Layer"]
    llm_api["LLM API Adapter"]
    llm_local["LLM Local Adapter"]
  end

  subgraph tts_layer["TTS Layer"]
    tts_api["TTS API Adapter"]
    tts_local["TTS Local Adapter"]
  end

  subgraph avatar_layer["Avatar Layer"]
    av_api["Avatar API Adapter"]
    av_local["Avatar Local Adapter"]
  end

  subgraph remote["Remote AI Providers"]
    openai["OpenAI/Qwen-Compatible Endpoint"]
    eleven["ElevenLabs/OpenAI TTS Endpoint"]
    avatar_saas["Tavus/HeyGen/D-ID Endpoint"]
  end

  subgraph local_workers["Local GPU Workers (Optional)"]
    qwen_local["Qwen3 via vLLM"]
    cosy_local["CosyVoice3/GLM-TTS"]
    muse_local["MuseTalk/LatentSync"]
  end

  client --> gateway
  gateway --> auth
  auth --> orchestrator
  orchestrator --> session
  orchestrator --> control
  orchestrator --> align
  orchestrator --> routing
  orchestrator --> mux
  mux --> gateway
  gateway --> client

  router --> llm_layer
  router --> tts_layer
  router --> avatar_layer
  fb --> router
  health --> router

  llm_api --> openai
  tts_api --> eleven
  av_api --> avatar_saas

  llm_local --> qwen_local
  tts_local --> cosy_local
  av_local --> muse_local

  gateway --> obs
  orchestrator --> obs
  routing --> obs
  align --> obs
```

## 2) Component Decomposition
```mermaid
flowchart TB
  subgraph api["app/api"]
    deps["deps.py"]
    rs["routes/sessions.py"]
    rstream["routes/stream.py"]
    rgen["routes/generate.py"]
    rh["routes/health.py"]
    rm["routes/models.py"]
    wsprot["ws/protocol.py"]
    wscodec["ws/event_codec.py"]
  end

  subgraph infra["app/infra"]
    cfg["config.py"]
    log["logging.py"]
    tele["telemetry.py"]
    errs["errors.py"]
    life["lifecycle.py"]
  end

  subgraph domain["app/domain"]
    dctl["controls.py"]
    devt["events.py"]
    dmed["media.py"]
    dsess["session.py"]
    dcaps["capabilities.py"]
  end

  subgraph orch["app/orchestration"]
    eng["turn_engine.py"]
    sbuf["sentence_buffer.py"]
    sess["session_store.py"]
    cxl["cancellation.py"]
    fb["fallback_policy.py"]
    budget["timeout_budget.py"]
  end

  subgraph control["app/control"]
    p_res["resolver.py"]
    p_persona["personas.py"]
    pmap["mappings/*"]
  end

  subgraph providers["app/providers"]
    pbase["base.py"]
    reg["registry.py"]
    pll["llm/*"]
    ptts["tts/*"]
    pav["avatar/*"]
  end

  subgraph align["app/alignment"]
    a_tl["timeline.py"]
    a_drift["drift_controller.py"]
  end

  subgraph obs["app/observability"]
    met["metrics.py"]
    trc["tracing.py"]
  end

  api --> infra
  api --> domain
  api --> orch
  orch --> control
  orch --> providers
  orch --> align
  api --> obs
  orch --> obs
```

## 3) Realtime Sequence (API-only Split Mode)
```mermaid
sequenceDiagram
  autonumber
  participant U as "User Client"
  participant G as "API Gateway"
  participant O as "Orchestrator"
  participant C as "Control Plane"
  participant L as "LLM API Adapter"
  participant LP as "LLM Provider"
  participant T as "TTS API Adapter"
  participant TP as "TTS Provider"
  participant A as "Avatar API Adapter"
  participant AP as "Avatar Provider"
  participant D as "Drift Controller"

  U->>G: "WS user_text + optional controls"
  G->>O: "UserTextEvent"
  O->>L: "infer_stream(text, context)"
  L->>LP: "LLM API request"
  LP-->>L: "text deltas + style hints"
  L-->>O: "planned response"
  O->>C: "merge persona + user controls + hints"
  C-->>O: "normalized controls"
  O->>T: "infer_stream(text, controls)"
  T->>TP: "stream TTS request"
  loop "for each audio chunk"
    TP-->>T: "audio chunk + timestamps"
    T-->>O: "AudioChunkEvent"
    O->>A: "send text/audio + controls"
    A->>AP: "avatar API streaming request"
    AP-->>A: "video frame chunk"
    A-->>O: "VideoFrameEvent"
    O->>D: "update(audio_ts, video_ts)"
    D-->>O: "drift correction hint"
    O-->>G: "audio_chunk + video_frame + metrics"
    G-->>U: "realtime stream"
  end
  U->>G: "interrupt"
  G->>O: "InterruptEvent"
  O-->>T: "cancel"
  O-->>A: "cancel"
  O-->>G: "turn_stopped"
```

## 4) Realtime Sequence (API-only Managed Avatar Mode)
```mermaid
sequenceDiagram
  autonumber
  participant U as "User Client"
  participant G as "API Gateway"
  participant O as "Orchestrator"
  participant L as "LLM API Adapter"
  participant LP as "LLM Provider"
  participant C as "Control Plane"
  participant A as "Managed Avatar API Adapter"
  participant AP as "Managed Avatar Provider"

  U->>G: "WS user_text + controls"
  G->>O: "UserTextEvent"
  O->>L: "infer_stream(text)"
  L->>LP: "LLM API request"
  LP-->>L: "response text"
  L-->>O: "response text"
  O->>C: "map controls to provider fields"
  C-->>O: "provider-specific control payload"
  O->>A: "start avatar stream with text + controls"
  A->>AP: "provider stream session request"
  AP-->>A: "synced audio/video chunks"
  A-->>O: "AudioChunkEvent + VideoFrameEvent"
  O-->>G: "stream chunks"
  G-->>U: "realtime playback"
```

## 5) Orchestrator Internals (Turn Engine)
```mermaid
flowchart TB
  inq["Inbound Event Queue"]
  validator["Schema + Auth Validator"]
  turn["Turn State Machine"]
  sched["Scheduler + Backpressure"]
  llm_stage["LLM Stage"]
  ctl_stage["Control Merge Stage"]
  tts_stage["TTS Stage"]
  avatar_stage["Avatar Stage"]
  drift_stage["Drift Correction Stage"]
  outq["Outbound Event Queue"]
  cancel["Cancellation Token Manager"]
  retry["Retry + Timeout Manager"]

  inq --> validator --> turn --> sched
  sched --> llm_stage --> ctl_stage --> tts_stage --> avatar_stage --> drift_stage --> outq

  turn --> cancel
  sched --> retry
  retry --> llm_stage
  retry --> tts_stage
  retry --> avatar_stage
  cancel --> tts_stage
  cancel --> avatar_stage
```

## 6) Control Plane Mapping Design
```mermaid
flowchart LR
  uc["User Controls"]
  persona["Persona Defaults"]
  llm_hints["LLM Style Hints"]
  caps["Provider Capabilities"]
  normalize["Control Normalizer"]
  map_tts["TTS Control Mapper"]
  map_avatar["Avatar Control Mapper"]
  degrade["Capability-Aware Degrader"]
  report["Applied/Downgraded Control Report"]

  uc --> normalize
  persona --> normalize
  llm_hints --> normalize
  normalize --> map_tts
  normalize --> map_avatar
  caps --> map_tts
  caps --> map_avatar
  map_tts --> degrade
  map_avatar --> degrade
  degrade --> report
```

## 7) Provider Routing and Failover
```mermaid
flowchart TD
  req["Inference Request"]
  pick["Pick Primary Provider"]
  health["Health Check"]
  cb{"Circuit Open?"}
  call["Call Provider"]
  ok{"Success?"}
  fallback{"Fallback Available?"}
  next["Switch to Next Provider"]
  fail["Return Degraded/Error Event"]
  done["Return Output + Metrics"]

  req --> pick --> health --> cb
  cb -- "yes" --> fallback
  cb -- "no" --> call --> ok
  ok -- "yes" --> done
  ok -- "no" --> fallback
  fallback -- "yes" --> next --> call
  fallback -- "no" --> fail
```

## 8) Session and Turn State Machine
```mermaid
stateDiagram-v2
  [*] --> "SessionCreated"
  "SessionCreated" --> "Idle"
  "Idle" --> "TurnPreparing": "user_text"
  "TurnPreparing" --> "LLMRunning"
  "LLMRunning" --> "TTSRunning"
  "TTSRunning" --> "AvatarRunning"
  "AvatarRunning" --> "StreamingOutput"
  "StreamingOutput" --> "TurnCompleted": "end_turn"
  "StreamingOutput" --> "Interrupted": "interrupt"
  "Interrupted" --> "Idle": "cancel_ack"
  "TurnCompleted" --> "Idle"
  "LLMRunning" --> "TurnError": "provider_error"
  "TTSRunning" --> "TurnError": "provider_error"
  "AvatarRunning" --> "TurnError": "provider_error"
  "TurnError" --> "Idle": "recoverable"
  "Idle" --> "SessionClosing": "close_session"
  "SessionClosing" --> [*]
```

## 9) Local MacBook API-only Deployment
```mermaid
flowchart LR
  subgraph mac["Local MacBook"]
    ui["Local Client UI"]
    api["API Gateway Process"]
    orch["Orchestrator Process"]
    redis["Redis (optional local)"]
    obs["Local Logs + Metrics Exporter"]
  end

  subgraph cloud["Remote Provider Cloud"]
    llm["LLM API"]
    tts["TTS API"]
    avatar["Avatar Streaming API"]
  end

  ui --> api --> orch
  orch --> llm
  orch --> tts
  orch --> avatar
  orch --> redis
  api --> obs
  orch --> obs
  avatar --> api
  tts --> api
```

## 10) Interface Contract Map
```mermaid
classDiagram
  class ModelAdapter {
    +load(config)
    +warmup()
    +infer_stream(input, control, context)
    +infer_batch(input, control)
    +health()
    +capabilities()
  }

  class LLMAdapter
  class TTSAdapter
  class AvatarAdapter
  class EmotionControl
  class CharacterControl
  class RenderControl
  class TurnAlignment

  ModelAdapter <|-- LLMAdapter
  ModelAdapter <|-- TTSAdapter
  ModelAdapter <|-- AvatarAdapter

  EmotionControl --> CharacterControl
  CharacterControl --> RenderControl
  TurnAlignment --> RenderControl
```

## 11) Overview Reading Order
1. Lean v1 single-service topology.
2. High-level architecture.
3. Component decomposition.
4. Realtime split and managed sequences.
5. Orchestrator internals.
6. Control mapping, failover, and session state machine.
7. Deployment topology.
8. Interface contract map.

## 12) API Gateway Detailed Design
```mermaid
flowchart TB
  ws["WebSocket Endpoint"]
  http["HTTP Endpoint"]
  auth["Auth Middleware"]
  rl["Rate Limiter"]
  vld["Schema Validator"]
  sid["Session ID Resolver"]
  router["Command Router"]
  shub["Stream Hub"]
  outbuf["Outbound Ring Buffer"]
  err["Error Mapper"]
  aud["Audit Logger"]
  met["Gateway Metrics"]

  ws --> auth
  http --> auth
  auth --> rl --> vld --> sid --> router
  router --> shub
  shub --> outbuf --> ws
  router --> http
  vld --> err
  err --> ws
  err --> http
  auth --> aud
  shub --> met
  rl --> met
```

## 13) Orchestrator Concurrency and Queues
```mermaid
flowchart LR
  subgraph ingress["Ingress"]
    inq["Inbound Event Queue"]
    parse["Event Parser"]
    turnsel["Turn Selector"]
  end

  subgraph workers["Per-Turn Worker Group"]
    plan["LLM Planner Task"]
    ctl["Control Merge Task"]
    tts["TTS Stream Task"]
    avatar["Avatar Stream Task"]
    drift["Drift Control Task"]
  end

  subgraph buffers["Realtime Buffers"]
    abuf["Audio Chunk Buffer"]
    vbuf["Video Frame Buffer"]
    mbuf["Metrics Buffer"]
  end

  outq["Outbound Queue"]
  cancel["Cancellation Token"]
  bp["Backpressure Controller"]

  inq --> parse --> turnsel --> plan --> ctl --> tts --> avatar --> drift
  tts --> abuf
  avatar --> vbuf
  drift --> mbuf
  abuf --> bp
  vbuf --> bp
  mbuf --> bp
  bp --> outq
  cancel --> tts
  cancel --> avatar
  cancel --> drift
```

## 14) LLM Component Detailed Flow
```mermaid
flowchart TB
  req["Turn Text + Context"]
  pb["Prompt Builder"]
  guard["Input Guardrails"]
  pri["Primary LLM Adapter"]
  fb["Fallback LLM Adapter"]
  parse["Structured Output Parser"]
  hint["Style Hint Extractor"]
  cache["Short-Lived Response Cache"]
  out["Planned Text + Hints"]

  req --> pb --> guard --> pri
  pri --> parse
  pri -. "timeout/error" .-> fb --> parse
  parse --> hint --> cache --> out
```

## 15) TTS Component Detailed Flow
```mermaid
flowchart LR
  txt["Response Text"]
  ctl["Emotion + Character Controls"]
  seg["Text Segmenter"]
  pros["Prosody Planner"]
  synth["Streaming Synthesizer"]
  pcm["PCM Chunk Stream"]
  ts["Timestamp Tagger"]
  res["Resampler + Encoder"]
  out["AudioChunkEvent"]

  txt --> seg --> pros --> synth --> pcm --> ts --> res --> out
  ctl --> pros
  ctl --> synth
```

## 16) Avatar Component Detailed Flow
```mermaid
flowchart LR
  a_in["Audio Chunks + Controls"]
  fe["Audio Feature Extractor"]
  cond["Expression + Motion Conditioner"]
  idlock["Identity Constraint"]
  render["Frame Generator"]
  post["Post Process"]
  pace["Frame Pacer"]
  enc["Video Encoder/Packager"]
  v_out["VideoFrameEvent"]

  a_in --> fe --> cond --> render --> post --> pace --> enc --> v_out
  cond --> idlock --> render
```

## 17) Alignment and Drift Control Loop
```mermaid
flowchart TB
  aud["Audio Timeline"]
  vid["Video Timeline"]
  measure["Drift Estimator"]
  policy["Correction Policy"]
  tts_adj["TTS Timing Adjust"]
  av_adj["Avatar Frame Adjust"]
  qos["QoS Monitor"]

  aud --> measure
  vid --> measure
  measure --> policy
  policy --> tts_adj
  policy --> av_adj
  tts_adj --> aud
  av_adj --> vid
  measure --> qos
```

## 18) Provider Circuit Breaker State Machine
```mermaid
stateDiagram-v2
  [*] --> "Closed"
  "Closed" --> "Open": "failure threshold reached"
  "Open" --> "HalfOpen": "cooldown elapsed"
  "HalfOpen" --> "Closed": "probe success"
  "HalfOpen" --> "Open": "probe failure"
```

## 19) Failure Recovery Sequence (Primary to Fallback)
```mermaid
sequenceDiagram
  autonumber
  participant O as "Orchestrator"
  participant R as "Provider Router"
  participant P1 as "Primary Provider"
  participant CB as "Circuit Breaker"
  participant P2 as "Fallback Provider"
  participant G as "Gateway"

  O->>R: "infer_stream(stage, payload)"
  R->>P1: "request"
  P1--xR: "timeout/error"
  R->>CB: "record failure"
  CB-->>R: "open or keep closed"
  R->>P2: "retry on fallback"
  P2-->>R: "success chunk stream"
  R-->>O: "stream + fallback metadata"
  O-->>G: "degraded_mode event + output"
```

## 20) Data and Observability Pipeline
```mermaid
flowchart LR
  gw["Gateway Logs"]
  orch["Orchestrator Logs"]
  prov["Provider Metrics"]
  qos["QoS Metrics"]
  trace["Trace Spans"]
  collector["OTel Collector"]
  prom["Prometheus"]
  graf["Grafana"]
  lake["Analytics Store"]
  alert["Alert Manager"]

  gw --> collector
  orch --> collector
  prov --> collector
  qos --> collector
  trace --> collector
  collector --> prom --> graf
  collector --> lake
  prom --> alert
```

## 21) Security and Trust Boundaries
```mermaid
flowchart TB
  subgraph client_zone["Client Zone"]
    client["Client App"]
  end

  subgraph service_zone["Trusted Service Zone"]
    gw["API Gateway"]
    orch["Orchestrator"]
    secrets["Secrets Manager"]
    policy["Policy Engine"]
  end

  subgraph provider_zone["External Provider Zone"]
    llm["LLM API"]
    tts["TTS API"]
    av["Avatar API"]
  end

  client -->|"TLS + API Key/JWT"| gw
  gw -->|"mTLS/Internal Auth"| orch
  orch -->|"scoped token"| llm
  orch -->|"scoped token"| tts
  orch -->|"scoped token"| av
  gw --> secrets
  orch --> secrets
  orch --> policy
```
