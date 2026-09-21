export const modelportEnglish = {
  'modelport.clientRequest':
    'Use your purchased model and API Key in your own client.',
  'modelport.deleteChannelModel':
    'This model comes from channel configuration. Delete removes this exact model from all channels and stops routing it. Other models, keys, balances and pricing remain unchanged.',
  'modelport.mailTest': 'Send test email',
  'modelport.mailSavedOnly':
    'Save your notification email first. The test uses the saved address, or your account email.',
  'modelport.mailAccepted':
    'The mail server accepted the test email. Check your inbox and spam folder; acceptance does not guarantee delivery.',
  'modelport.mailUnavailable':
    'Email delivery is not configured. Ask the administrator to configure SMTP and permitted network access.',
  'modelport.mailMissingRecipient':
    'Enter and save a notification email, or use a bound account email.',
  'modelport.mailFailed':
    'Could not send the test email. Check saved settings or contact the administrator.',
}

export const modelportChinese: Record<keyof typeof modelportEnglish, string> = {
  'modelport.clientRequest':
    '在自己的客户端中使用已购买的模型和 API Key 发起请求。',
  'modelport.deleteChannelModel':
    '此模型来自渠道配置。删除会从所有渠道移除这个精确模型并停止路由；其他模型、客户 Key、余额和价格配置保持不变。',
  'modelport.mailTest': '发送测试邮件',
  'modelport.mailSavedOnly':
    '请先保存通知邮箱。测试使用已保存的通知邮箱，留空时使用已绑定的账户邮箱。',
  'modelport.mailAccepted':
    '邮件服务器已接受测试邮件，请检查收件箱和垃圾邮件。服务器接受不等于邮件已送达。',
  'modelport.mailUnavailable':
    '邮件发送尚未配置，请联系管理员设置 SMTP 及获准的网络访问。',
  'modelport.mailMissingRecipient':
    '请填写并保存通知邮箱，或先使用已绑定的账户邮箱。',
  'modelport.mailFailed': '测试邮件发送失败，请检查已保存的设置或联系管理员。',
}
