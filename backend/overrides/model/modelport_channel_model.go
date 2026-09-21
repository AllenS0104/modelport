package model

import (
	"errors"
	"strings"

	"gorm.io/gorm"
)

// Channel-derived list entries have no metadata ID. Remove the exact routing name
// transactionally, without creating metadata or deleting unrelated channel data.
func ModelPortDeleteChannelModel(name string) (ModelDeleteResult, error) {
	result := ModelDeleteResult{}
	if name == "" || name != strings.TrimSpace(name) || len(name) > 255 || strings.ContainsAny(name, ",\r\n") {
		return result, errors.New("无效的模型名称，请刷新后重试")
	}
	err := metadataTransaction(func(tx *gorm.DB) error {
		var records []Model
		if err := lockForUpdate(tx).Find(&records).Error; err != nil {
			return err
		}
		for _, record := range records {
			if record.MatchesName(name) {
				return errors.New("模型元数据已变更，请刷新后使用模型记录的删除操作")
			}
		}
		var channels []Channel
		if err := lockForUpdate(tx).Select("id", "models", "status", "group", "priority", "weight", "tag").
			Order("id").Find(&channels).Error; err != nil {
			return err
		}
		for _, channel := range channels {
			names := channel.GetModels()
			remaining := make([]string, 0, len(names))
			for _, item := range names {
				if strings.TrimSpace(item) != name {
					remaining = append(remaining, item)
				}
			}
			if len(names) == len(remaining) {
				continue
			}
			channel.Models = strings.Join(remaining, ",")
			if err := tx.Model(&Channel{}).Where("id = ?", channel.Id).Update("models", channel.Models).Error; err != nil {
				return err
			}
			if err := channel.UpdateAbilities(tx); err != nil {
				return err
			}
			result.UpdatedChannels++
		}
		if result.UpdatedChannels == 0 {
			return errors.New("该模型已不在渠道中，请刷新模型列表")
		}
		result.DeletedCount = 1
		return nil
	})
	if err != nil {
		return ModelDeleteResult{}, err
	}
	InitChannelCache()
	RefreshPricing()
	return result, nil
}
