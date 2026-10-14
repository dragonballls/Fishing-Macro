$ErrorActionPreference = 'Stop'
$secureKey = $null
$apiKey = $null
$ptr = [IntPtr]::Zero
$bitmap = $null
$graphics = $null
$stream = $null

try {
    $secureKey = Read-Host 'Gemini API key (hidden; not saved)' -AsSecureString
    if ($null -eq $secureKey -or $secureKey.Length -eq 0) { throw 'No API key was entered.' }

    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $ptr = [IntPtr]::Zero

    # Synthetic image only. No Roblox/game screenshot is captured or uploaded.
    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new(2, 2)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::DodgerBlue)
    $stream = [System.IO.MemoryStream]::new()
    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $image = [Convert]::ToBase64String($stream.ToArray())

    $schema = @{
        type = 'OBJECT'
        properties = @{
            screen_state = @{ type = 'STRING'; enum = @('normal_gameplay','reel_minigame','bite_marker','charge_meter','catch_popup','learn_popup','npc_root_menu','npc_shop_menu','npc_bait_menu','craft_window','interact_prompt','unknown') }
            summary = @{ type = 'STRING' }
            next_instruction = @{ type = 'STRING' }
            regions = @{ type = 'ARRAY'; items = @{
                type = 'OBJECT'
                properties = @{
                    key = @{ type = 'STRING'; enum = @('bar_search','zone_track','bite','meter','popup','learn','learn_click','menu','center','menu_item1','menu_item2','menu_item3','menu_last','craft_btn','craft_plus','craft_button','craft_close') }
                    kind = @{ type = 'STRING'; enum = @('box','dot') }
                    coords = @{ type = 'ARRAY'; items = @{ type = 'NUMBER' } }
                    confidence = @{ type = 'NUMBER' }
                    evidence = @{ type = 'STRING' }
                }
                required = @('key','kind','coords','confidence','evidence')
            }}
        }
        required = @('screen_state','summary','next_instruction','regions')
    }

    $body = @{
        contents = @(@{ parts = @(
            @{ text = 'Live API smoke test only. Inspect the synthetic image and return screen_state unknown, summary, next_instruction, and an empty regions array. Do not infer game controls.' }
            @{ inline_data = @{ mime_type = 'image/png'; data = $image } }
        )})
        generationConfig = @{
            responseMimeType = 'application/json'
            responseSchema = $schema
            maxOutputTokens = 600
        }
    } | ConvertTo-Json -Depth 24 -Compress

    $response = Invoke-RestMethod -Uri 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent' -Method Post -Headers @{ 'x-goog-api-key' = $apiKey } -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 45
    $text = (($response.candidates[0].content.parts | ForEach-Object { $_.text }) -join "`n").Trim()
    $answer = $text | ConvertFrom-Json
    foreach ($field in @('screen_state','summary','next_instruction','regions')) {
        if ($null -eq $answer.PSObject.Properties[$field]) { throw "Gemini responded, but field '$field' was missing from the structured JSON." }
    }

    Write-Host ''
    Write-Host 'PASS: Gemini accepted the key, image input, and structured calibration schema.' -ForegroundColor Green
    Write-Host ("Model: gemini-3.8-flash; returned state: {0}; proposed regions: {1}" -f $answer.screen_state, @($answer.regions).Count)
    Write-Host 'Only a tiny synthetic image was uploaded; no Roblox screenshot was used.'
    Write-Host 'This verifies live API access, not the full visual calibration session.'
}
catch {
    $detail = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        try {
            $apiError = $_.ErrorDetails.Message | ConvertFrom-Json
            if ($apiError.error.message) { $detail = [string]$apiError.error.message }
        } catch { }
    }
    Write-Host ''
    Write-Host 'FAIL: The Gemini live test did not complete.' -ForegroundColor Red
    Write-Host ("Details: {0}" -f $detail)
    Write-Host 'Share the error text only, never your API key.'
}
finally {
    if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if ($graphics) { $graphics.Dispose() }
    if ($bitmap) { $bitmap.Dispose() }
    if ($stream) { $stream.Dispose() }
    $apiKey = $null
    $secureKey = $null
    $body = $null
    $image = $null
    [GC]::Collect()
}
