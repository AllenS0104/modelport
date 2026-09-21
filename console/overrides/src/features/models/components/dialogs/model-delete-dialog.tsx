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
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import {
  useCanEditModelPricing,
  invalidateModelPricing,
} from '@/features/model-pricing/api'
import { api } from '@/lib/api'
import { createServerError } from '@/lib/server-error-message'

import { deleteModel, deleteModels } from '../../api'
import type { Model } from '../../types'
import { invalidateVendorData } from '../../vendor-api'

interface ModelDeleteDialogProps {
  models: Pick<Model, 'id' | 'model_name' | 'name_rule'>[]
  onClose: () => void
  onSuccess?: () => void
}

export function ModelDeleteDialog(props: ModelDeleteDialogProps) {
  const { t } = useTranslation()
  const checkboxId = useId()
  const pricingCheckboxId = useId()
  const canEditPricing = useCanEditModelPricing()
  const channelOnly = props.models.length === 1 && props.models[0].id === 0
  const supportsChannelRemoval = props.models.every(
    (model) => model.name_rule === 0
  )
  const [removePricing, setRemovePricing] = useState(false)
  const [removeFromChannels, setRemoveFromChannels] = useState(channelOnly)
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: async () => {
      const ids = props.models.map((model) => model.id)
      let response
      if (channelOnly) {
        const result = await api.post<{
          success: boolean
          message?: string
          data: { deleted_count: number; updated_channels: number }
        }>('/api/models/channel-only/delete', {
          model_name: props.models[0].model_name,
        })
        response = result.data
      } else {
        response =
          ids.length === 1
            ? await deleteModel(
                ids[0],
                removeFromChannels && supportsChannelRemoval,
                removePricing && canEditPricing
              )
            : await deleteModels(
                ids,
                removeFromChannels && supportsChannelRemoval,
                removePricing && canEditPricing
              )
      }
      if (!response.success) {
        throw createServerError(response, t('Failed to delete model'))
      }
      return response.data
    },
    onSuccess: async (result) => {
      await invalidateVendorData(client)
      if (removePricing) await invalidateModelPricing(client)
      if (removeFromChannels) {
        await client.invalidateQueries({ queryKey: ['channels'] })
      }
      toast.success(
        t('Successfully deleted {{count}} model(s)', {
          count: result.deleted_count,
        })
      )
      props.onSuccess?.()
      props.onClose()
    },
  })
  const description =
    props.models.length === 1
      ? t('Delete model "{{name}}"?', { name: props.models[0].model_name })
      : t('Delete {{count}} models?', { count: props.models.length })
  let errorMessage = mutation.error?.message
  if (isAxiosError<{ message?: string }>(mutation.error)) {
    errorMessage = mutation.error.response?.data.message || errorMessage
  }
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => {
        if (!open && !mutation.isPending) props.onClose()
      }}
      title={t('Delete Models?')}
      desc={description}
      confirmText={t('Delete')}
      destructive
      disabled={!props.models.length}
      isLoading={mutation.isPending}
      handleConfirm={() => mutation.mutate()}
    >
      <div className='space-y-3'>
        {channelOnly && (
          <p className='text-muted-foreground text-sm'>
            {t('modelport.deleteChannelModel')}
          </p>
        )}
        <div className='flex items-start gap-2'>
          <Checkbox
            id={checkboxId}
            className='mt-0.5'
            checked={removeFromChannels && supportsChannelRemoval}
            disabled={
              mutation.isPending || !supportsChannelRemoval || channelOnly
            }
            onCheckedChange={(checked) =>
              setRemoveFromChannels(checked === true)
            }
          />
          <Label htmlFor={checkboxId} className='flex-wrap leading-normal'>
            {t('Also remove from all channels')}
            {!supportsChannelRemoval && (
              <span className='text-muted-foreground text-xs font-normal'>
                {t('Only available for exact matching')}
              </span>
            )}
          </Label>
        </div>
        <div className='flex items-start gap-2'>
          <Checkbox
            id={pricingCheckboxId}
            className='mt-0.5'
            checked={removePricing}
            disabled={mutation.isPending || !canEditPricing || channelOnly}
            onCheckedChange={(checked) => setRemovePricing(checked === true)}
          />
          <Label htmlFor={pricingCheckboxId} className='leading-normal'>
            {t('Also remove pricing')}
          </Label>
        </div>
        {(removePricing || !canEditPricing) && (
          <p className='text-muted-foreground text-sm'>
            {canEditPricing
              ? t('Built-in pricing may become effective again.')
              : t('Model pricing is managed by a super administrator.')}
          </p>
        )}
        {mutation.isError && (
          <p role='alert' className='text-destructive text-sm'>
            {errorMessage || t('Failed to delete model')}
          </p>
        )}
      </div>
    </ConfirmDialog>
  )
}
