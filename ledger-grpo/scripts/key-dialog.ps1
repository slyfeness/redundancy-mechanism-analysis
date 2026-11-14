Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[System.Windows.Forms.Application]::EnableVisualStyles()
$keyForm = [System.Windows.Forms.Form]::new()
$keyForm.Text = 'DeepSeek API key'
$keyForm.StartPosition = 'CenterScreen'
$keyForm.ClientSize = [System.Drawing.Size]::new(590, 175)
$keyForm.FormBorderStyle = 'FixedDialog'
$keyForm.MaximizeBox = $false
$keyForm.MinimizeBox = $false
$keyForm.TopMost = $true
$keyForm.Font = [System.Drawing.Font]::new('Microsoft YaHei UI', 10)
$keyLabel = [System.Windows.Forms.Label]::new()
$keyLabel.Text = '粘贴 DeepSeek 官方 API key（支持 Ctrl+V），然后点击确认。'
$keyLabel.SetBounds(18, 18, 555, 30)
$keyInput = [System.Windows.Forms.TextBox]::new()
$keyInput.UseSystemPasswordChar = $true
$keyInput.ShortcutsEnabled = $true
$keyInput.SetBounds(18, 55, 550, 30)
$keyNote = [System.Windows.Forms.Label]::new()
$keyNote.Text = '认证成功后，用当前 Windows 用户加密保存，后续自动复用。'
$keyNote.SetBounds(18, 92, 550, 25)
$keyConfirm = [System.Windows.Forms.Button]::new()
$keyConfirm.Text = '确认'
$keyConfirm.SetBounds(375, 130, 90, 30)
$keyConfirm.DialogResult = [System.Windows.Forms.DialogResult]::OK
$keyCancel = [System.Windows.Forms.Button]::new()
$keyCancel.Text = '取消'
$keyCancel.SetBounds(478, 130, 90, 30)
$keyCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$keyForm.Controls.AddRange(@($keyLabel, $keyInput, $keyNote, $keyConfirm, $keyCancel))
$keyForm.AcceptButton = $keyConfirm
$keyForm.CancelButton = $keyCancel
$keyForm.Add_Shown({ [void]$keyInput.Focus() })
try {
    if ($keyForm.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        # Captured only by the parent Python pipe; never run this script standalone.
        [Console]::Write($keyInput.Text)
    } else {
        exit 130
    }
} finally {
    $keyInput.Clear()
    $keyForm.Dispose()
}
