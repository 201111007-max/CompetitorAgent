import { defineStore } from 'pinia'
import type { LogEntry } from '@/types/log'

export const useLogStore = defineStore('log', {
  state: () => ({
    entries: [] as LogEntry[],
    filter: {
      level: 'ALL',
      search: ''
    }
  }),

  getters: {
    filteredEntries: (state) => {
      let filtered = state.entries

      if (state.filter.level !== 'ALL') {
        filtered = filtered.filter(entry => entry.level === state.filter.level)
      }

      if (state.filter.search) {
        const searchLower = state.filter.search.toLowerCase()
        filtered = filtered.filter(entry =>
          entry.message.toLowerCase().includes(searchLower) ||
          entry.component?.toLowerCase().includes(searchLower)
        )
      }

      return filtered
    }
  },

  actions: {
    addEntry(entry: LogEntry) {
      this.entries.push(entry)
      if (this.entries.length > 1000) {
        this.entries = this.entries.slice(-500)
      }
    },

    setEntries(entries: LogEntry[]) {
      this.entries = entries
    },

    setFilter(filter: Partial<typeof this.filter>) {
      this.filter = { ...this.filter, ...filter }
    },

    clearEntries() {
      this.entries = []
    }
  }
})
