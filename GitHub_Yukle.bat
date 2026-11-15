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

git remote get-url origin >nul 2>nul
if errorlevel 1 (
    echo.
    echo GitHub'da BOS yeni bir depo olusturun ^(ornek: HaneButcesiV2^)
    echo ve adresini buraya yapistirin ^(https://github.com/KULLANICI/HaneButcesiV2.git^)
    set /p REPO_URL=Depo adresi:
    call git remote add origin %%REPO_URL%%
)

if exist "build-apk.yml" (
    if not exist ".github\workflows" mkdir ".github\workflows"
    copy /y "build-apk.yml" ".github\workflows\build-apk.yml" >nul
)

git add main.py hb_core.py requirements.txt supabase_kurulum.sql KURULUM.md .gitignore GitHub_Yukle.bat build-apk.yml .github
set TARIH=%date% %time%
git commit -m "Guncelleme: %TARIH%" --allow-empty
git push -u origin main

echo.
echo ===================================================================
echo  Tamam! GitHub ^> Actions sekmesinden derlemeyi izleyin (~10 dk).
echo  Bitince Releases ^> latest altindan HaneButcesi_v2.apk indirilir.
echo ===================================================================
pause
