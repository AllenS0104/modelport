package model

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestModelPortChannelRemovalRollsBackRoutingOnFailure(t *testing.T) {
	setupChannelStatusTest(t)
	require.NoError(t, DB.AutoMigrate(&Model{}, &Option{}))
	for _, id := range []int{1, 2} {
		channel := Channel{Id: id, Name: "fixture", Key: "fixture-key", Models: "remove,retain", Group: "default", Status: 1}
		require.NoError(t, DB.Create(&channel).Error)
		require.NoError(t, channel.UpdateAbilities(DB))
	}
	for _, name := range []string{"", " remove", "remove,retain", "remove\n", "absent"} {
		_, err := ModelPortDeleteChannelModel(name)
		require.Error(t, err)
	}
	require.NoError(t, DB.Exec(`CREATE TRIGGER fixture_fail_second
		BEFORE UPDATE OF models ON channels WHEN OLD.id = 2
		BEGIN SELECT RAISE(ABORT, 'fixture rollback'); END`).Error)
	t.Cleanup(func() { require.NoError(t, DB.Exec("DROP TRIGGER fixture_fail_second").Error) })
	_, err := ModelPortDeleteChannelModel("remove")
	require.ErrorContains(t, err, "fixture rollback")
	var channels []Channel
	require.NoError(t, DB.Order("id").Find(&channels).Error)
	require.Len(t, channels, 2)
	for _, channel := range channels {
		require.Equal(t, "remove,retain", channel.Models)
		require.Equal(t, "fixture-key", channel.Key)
	}
	var abilities int64
	require.NoError(t, DB.Model(&Ability{}).Where("model = ?", "remove").Count(&abilities).Error)
	require.EqualValues(t, 2, abilities)
}
