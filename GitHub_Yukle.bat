@echo off
chcp 65001 >nul
title Hane Butcesi v2 - GitHub'a Yukle ve APK Derle
color 0B
cd /d "%~dp0"

echo ===================================================================
echo        HANE BUTCESI v2 - GITHUB'A YUKLE (APK otomatik derlenir)
echo ===================================================================
echo Calisma dizini: %cd%
echo.

git config --global --add safe.directory "%cd%" >nul 2>nul

if not exist ".git" (
    echo Ilk kurulum: yeni bir git deposu olusturuluyor...
    git init -b main
)

set "DOGRU_URL=https://github.com/abdurrahmancosk/HaneButcesiV2.git"
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    git remote add origin "%DOGRU_URL%"
) else (
    git remote set-url origin "%DOGRU_URL%"
)

echo Depo adresi:
git remote get-url origin
echo.

if exist "build-apk.yml" (
    if not exist ".github\workflows" mkdir ".github\workflows"
    copy /y "build-apk.yml" ".github\workflows\build-apk.yml" >nul
)

git add main.py hb_core.py requirements.txt supabase_kurulum.sql eski_veri_aktar.sql KURULUM.md .gitignore GitHub_Yukle.bat EXE_Indir.ps1 build-apk.yml .github
set "TARIH=%date% %time%"
git commit -m "Guncelleme: %TARIH%" --allow-empty
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('o')"`) do set "PUSH_ZAMANI=%%t"
git push -u origin main
if errorlevel 1 goto HATA

echo.
echo Yukleme tamam. Derleme bitince HaneButcesi.exe bu klasore otomatik indirilecek.
echo (Pencereyi kapatmayin; APK icin GitHub ^> Releases sayfasina bakin.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0EXE_Indir.ps1" -Sonra "%PUSH_ZAMANI%"

echo.
echo ===================================================================
echo  Telefon APK: https://github.com/abdurrahmancosk/HaneButcesiV2/releases/latest
echo  Bilgisayar EXE: bu klasordeki HaneButcesi.exe
echo ===================================================================
pause
exit /b 0

:HATA
echo.
echo ===================================================================
echo  HATA: GitHub'a yuklenemedi!
echo  https://github.com/new adresinden "HaneButcesiV2" adinda BOS bir
echo  depo actiginizdan emin olun (README eklemeyin), sonra bu dosyayi
echo  tekrar calistirin.
echo ===================================================================
pause
exit /b 1
