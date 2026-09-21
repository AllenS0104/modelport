/*
Copyright (C) 2023-2026 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/
import { useTranslation } from 'react-i18next'

import { PlatformAttribution, PlatformBrand } from '@/components/platform-brand'
import { Skeleton } from '@/components/ui/skeleton'
import { useSystemConfig } from '@/hooks/use-system-config'

type AuthLayoutProps = {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  const { t } = useTranslation()
  const { systemName, logo, loading } = useSystemConfig()

  return (
    <div className='modelport-auth'>
      <header className='modelport-auth-header'>
        <a href='/h5/' aria-label={t('Go to home')}>
          <PlatformBrand />
        </a>
        <nav aria-label={t('Navigation')}>
          <a href='/h5/#models'>{t('Model Square')}</a>
          <a href='/h5/#guide'>{t('Docs')}</a>
          <a href='/dashboard/models'>{t('Dashboard')}</a>
        </nav>
      </header>
      <main className='modelport-auth-card'>
        <div className='modelport-upstream mb-5'>
          <div className='relative h-4 w-4'>
            {loading ? (
              <Skeleton className='absolute inset-0 rounded-full' />
            ) : (
              <img
                src={logo}
                alt={t('Logo')}
                className='h-4 w-4 rounded-full object-cover'
              />
            )}
          </div>
          {loading ? (
            <Skeleton className='h-6 w-24' />
          ) : (
            <span>Powered by {systemName}</span>
          )}
        </div>
        <div className='flex w-full flex-col justify-center space-y-2'>
          {children}
        </div>
      </main>
      <PlatformAttribution />
    </div>
  )
}
