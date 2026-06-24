export interface GSIAbility {
  name: string
  level: number
  can_cast: boolean
  passive: boolean
  cooldown: number
  ultimate: boolean
}

export interface GSIItem {
  name: string
  slot: string
  can_cast: boolean
  cooldown: number
  charges: number
}

export interface GSIGameState {
  map_name: string
  match_id: string
  game_time: number
  clock_time: number
  daytime: boolean
  radiant_score: number
  dire_score: number
  game_state: string
  paused: boolean
  win_team: string
  player_name: string
  steam_id: string
  kills: number
  deaths: number
  assists: number
  last_hits: number
  denies: number
  gold: number
  gold_reliable: number
  gpm: number
  xpm: number
  hero_name: string
  hero_id: number
  level: number
  alive: boolean
  respawn_seconds: number
  health: number
  max_health: number
  mana: number
  max_mana: number
  buyback_cost: number
  abilities: GSIAbility[]
  inventory: GSIItem[]
  updated_at: number
}

export interface GSIEvent {
  event_type: string
  message: string
  priority: 'info' | 'warning' | 'critical'
  data: Record<string, unknown>
  timestamp: number
}

export interface GSIStateResponse {
  available: boolean
  connected: boolean
  state?: GSIGameState
  message?: string
}

export interface Recommendation {
  event_type: string
  event_message: string
  recommendation: {
    recommendation: string
    confidence: number
    sources: string[]
    conflict_detected: boolean
  }
  timestamp: number
}

export interface RecommendationStatus {
  available: boolean
  status?: {
    enabled: boolean
    running: boolean
    event_queue_set: boolean
    decision_fusion_set: boolean
    state_manager_set: boolean
    push_callback_set: boolean
    cooldowns: Record<string, number>
  }
  message?: string
}
