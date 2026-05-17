export interface HeroInfo {
  id: string
  cn: string
  en: string
}

export interface HeroQuery {
  query: string
  our_heroes: string[]
  enemy_heroes: string[]
}

export interface HeroState {
  heroes: HeroInfo[]
  currentQuery: HeroQuery | null
  isLoading: boolean
  error: string | null
}
