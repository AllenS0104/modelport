import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { createServerError } from '@/lib/server-error-message'

interface EmailReadiness {
  configured: boolean
  recipient_configured: boolean
}

export function NotificationEmailTest(props: {
  profileId: number
  setting?: string
}) {
  const { t } = useTranslation()
  const readiness = useQuery({
    queryKey: ['modelport-email', props.profileId, props.setting],
    queryFn: async () => {
      const response = await api.get<{
        success: boolean
        data: EmailReadiness
      }>('/api/user/notification/email')
      if (!response.data.success) {
        throw createServerError(response.data, t('modelport.mailFailed'))
      }
      return response.data.data
    },
    retry: false,
  })
  const send = useMutation({
    mutationFn: async () => {
      const response = await api.post('/api/user/notification/email/test')
      if (!response.data.success) {
        throw createServerError(response.data, t('modelport.mailFailed'))
      }
    },
    onSuccess: () => toast.success(t('modelport.mailAccepted')),
  })

  return (
    <div className='space-y-2'>
      <p className='text-muted-foreground text-xs'>
        {t('modelport.mailSavedOnly')}
      </p>
      {readiness.data?.configured === false && (
        <p role='status' className='text-sm'>
          {t('modelport.mailUnavailable')}
        </p>
      )}
      {readiness.data?.recipient_configured === false && (
        <p role='status' className='text-sm'>
          {t('modelport.mailMissingRecipient')}
        </p>
      )}
      {(readiness.isError || send.isError) && (
        <p role='alert' className='text-destructive text-sm'>
          {t('modelport.mailFailed')}
        </p>
      )}
      <Button
        type='button'
        variant='outline'
        disabled={
          send.isPending ||
          !readiness.data?.configured ||
          !readiness.data?.recipient_configured
        }
        onClick={() => send.mutate()}
      >
        {t('modelport.mailTest')}
      </Button>
    </div>
  )
}
