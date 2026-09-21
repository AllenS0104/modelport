import { useTranslation } from 'react-i18next'

export const PLATFORM_NAME = '模港 ModelPort'

export function PlatformBrand() {
  return (
    <span className='modelport-brand' data-platform-brand>
      <span className='modelport-mark' aria-hidden='true'>
        MP
      </span>
      <span>{PLATFORM_NAME}</span>
    </span>
  )
}

export function PlatformAttribution() {
  const { t } = useTranslation()
  return (
    <footer className='modelport-attribution'>
      <span>Frontend design and development by New API contributors.</span>
      <a href='https://github.com/QuantumNous/new-api' rel='noreferrer'>
        Powered by New API · QuantumNous
      </a>
      <a href='/console-assets/modelport-source.tar.gz'>
        {t('Source code')} · AGPLv3
      </a>
    </footer>
  )
}
