export interface LogEntry {
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
  message: string
  component?: string
  logger_name?: string
  extra?: Record<string, any>
}

export interface LogState {
  entries: LogEntry[]
  filter: {
    level: string
    search: string
  }
}
