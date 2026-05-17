import { createDiscreteApi, darkTheme } from 'naive-ui'

const { message } = createDiscreteApi(['message'], {
  configProviderProps: {
    theme: darkTheme
  }
})

export { message }
