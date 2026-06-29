import { useState, useEffect, useCallback, useRef } from "react";
import { subscribeEvents, replayEvents, type AgentEvent, type AnalysisTrace, type AnalysisRound, type FinalResult } from "../api";



export function reduceAgentEvent(prev: AnalysisTrace, normalizedEvent: AgentEvent, eventName: string, eventData: any): AnalysisTrace {
  const draft = { ...prev };
  
  // Deduplicate raw events based on timestamp + event + data
  const evKey = `${normalizedEvent.timestamp ?? ""}|${normalizedEvent.event}|${JSON.stringify(normalizedEvent.data ?? {})}`;
  if (draft.rawEvents.some(e => `${e.timestamp ?? ""}|${e.event}|${JSON.stringify(e.data ?? {})}` === evKey)) {
    return prev;
  }
  
  draft.rawEvents = [...draft.rawEvents, normalizedEvent];

  switch (eventName) {
    case "task_started":
      break;
    case "video_started":
      if (eventData.duration_sec != null) draft.videoDurationSec = eventData.duration_sec;
      if (eventData.initial_candidate) draft.initialCandidate = eventData.initial_candidate;
      break;
    case "round_started": {
      const roundId = eventData.round ?? (draft.rounds.length + 1);
      const displayRound = eventData.display_round ?? roundId;
      const newRound: AnalysisRound = {
        round: roundId,
        displayRound: displayRound,
        stateAtStart: eventData.state,
        candidateAtStart: eventData.candidate
      };
      const existingIdx = draft.rounds.findIndex(r => r.round === roundId);
      if (existingIdx >= 0) {
        draft.rounds[existingIdx] = { ...draft.rounds[existingIdx], ...newRound };
      } else {
        draft.rounds.push(newRound);
      }
      break;
    }
    case "llm_tool_call": {
      const roundId = eventData.round ?? draft.rounds[draft.rounds.length - 1]?.round;
      if (roundId != null) {
        const idx = draft.rounds.findIndex(r => r.round === roundId);
        if (idx >= 0) {
          draft.rounds[idx].toolCall = {
            name: eventData.tool_name,
            args: eventData.tool_args || {},
            reasoning: eventData.reasoning
          };
        }
      }
      break;
    }
    case "sample_and_infer_started": {
      const roundId = eventData.round ?? draft.rounds[draft.rounds.length - 1]?.round;
      if (roundId != null) {
        const idx = draft.rounds.findIndex(r => r.round === roundId);
        if (idx >= 0) {
          draft.rounds[idx].sampleRange = eventData.sample_range;
        }
      }
      break;
    }
    case "sample_and_infer_finished": {
      const roundId = eventData.round ?? draft.rounds[draft.rounds.length - 1]?.round;
      if (roundId != null) {
        const idx = draft.rounds.findIndex(r => r.round === roundId);
        if (idx >= 0) {
          draft.rounds[idx].modelOutput = eventData.model_output;
          draft.rounds[idx].inferredTimeRange = eventData.inferred_time_range;
          draft.rounds[idx].validationError = eventData.validation_error;
          draft.rounds[idx].confidenceLevel = eventData.round_confidence_level;
        }
      }
      break;
    }
    case "state_updated": {
      const roundId = eventData.round ?? draft.rounds[draft.rounds.length - 1]?.round;
      if (roundId != null) {
        const idx = draft.rounds.findIndex(r => r.round === roundId);
        if (idx >= 0) {
          draft.rounds[idx].previousState = eventData.previous_state;
          draft.rounds[idx].nextState = eventData.state;
          draft.rounds[idx].previousCandidate = eventData.previous_candidate;
          draft.rounds[idx].nextCandidate = eventData.candidate;
        }
      }
      break;
    }
    case "termination_requested": {
      const roundId = eventData.round ?? draft.rounds[draft.rounds.length - 1]?.round;
      if (roundId != null) {
        const idx = draft.rounds.findIndex(r => r.round === roundId);
        if (idx >= 0) {
          draft.rounds[idx].terminationRequest = {
            allowed: eventData.allowed,
            reason: eventData.reason,
            args: eventData.tool_args || {}
          };
        }
      }
      break;
    }
    case "video_finished":
      if (eventData.result) {
        draft.finalResult = { ...draft.finalResult, ...eventData.result } as FinalResult;
      }
      break;
    case "video_failed":
      draft.taskError = { 
        stage: eventData.stage, 
        code: eventData.code ?? eventData.error, 
        message: eventData.message ?? String(eventData.error) 
      };
      break;
    case "task_completed":
      if (eventData.result) {
        draft.finalResult = { ...draft.finalResult, ...eventData.result } as FinalResult;
      }
      break;
    case "task_failed":
      draft.taskError = { 
        stage: eventData.stage, 
        code: eventData.code, 
        message: eventData.message ?? "Unknown error" 
      };
      break;
    case "ping":
      break;
    default:
      break;
  }
  return draft;
}

export function useAgentTaskEvents(taskId: string | null) {
  const [trace, setTrace] = useState<AnalysisTrace>({
    taskId: "",
    videoDurationSec: null,
    initialCandidate: null,
    rounds: [],
    finalResult: null,
    taskError: null,
    connectionState: "closed",
    rawEvents: []
  });

  const stateRef = useRef<AnalysisTrace>(trace);
  const reconnectTimeout = useRef<number | undefined>(undefined);

  const resetState = useCallback((id: string) => {
    const newState: AnalysisTrace = {
      taskId: id,
      videoDurationSec: null,
      initialCandidate: null,
      rounds: [],
      finalResult: null,
      taskError: null,
      connectionState: "connecting",
      rawEvents: []
    };
    setTrace(newState);
    stateRef.current = newState;
  }, []);

  const processEvent = useCallback((rawEvent: AgentEvent | any) => {
    const eventName = rawEvent.data?.event_type ?? rawEvent.event;
    const eventData = rawEvent.data ?? {};
    
    // Normalize raw event payload format
    const normalizedEvent: AgentEvent = {
      event: eventName,
      timestamp: rawEvent.timestamp,
      data: eventData
    };

    setTrace(prev => {
      const draft = reduceAgentEvent(prev, normalizedEvent, eventName, eventData);
      stateRef.current = draft;
      return draft;
    });
  }, []);


  useEffect(() => {
    if (!taskId) {
      setTrace({
        taskId: "",
        videoDurationSec: null,
        initialCandidate: null,
        rounds: [],
        finalResult: null,
        taskError: null,
        connectionState: "closed",
        rawEvents: []
      });
      return;
    }

    resetState(taskId);

    let isSubscribed = true;
    let cleanupSse: (() => void) | undefined;

    const loadHistoryAndSubscribe = async () => {
      try {
        const events = await replayEvents(taskId);
        if (!isSubscribed) return;
        
        events.forEach(ev => processEvent(ev));

        // Subscribing to new events
        setTrace(prev => ({ ...prev, connectionState: "open" }));
        cleanupSse = subscribeEvents(taskId, (ev: unknown) => {
          if (!isSubscribed) return;
          processEvent(ev);
        });
      } catch (err) {
        console.error("Failed to load events:", err);
        if (isSubscribed) {
          setTrace(prev => ({ ...prev, connectionState: "error" }));
        }
      }
    };

    loadHistoryAndSubscribe();

    return () => {
      isSubscribed = false;
      if (cleanupSse) cleanupSse();
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
    };
  }, [taskId, processEvent, resetState]);

  return trace;
}
