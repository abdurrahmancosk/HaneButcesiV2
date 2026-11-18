@echo off
chcp 65001 >nul
title Hane Butcesi - Kalici APK imzasi (tek seferlik)
color 0E
cd /d "%~dp0"
setlocal

set "DEPO=abdurrahmancosk/HaneButcesiV2"
set "SAYFA=https://github.com/%DEPO%/settings/secrets/actions/new"
set "B64=imza\ANDROID_KEYSTORE_BASE64.txt"
set "SIF=imza\ANDROID_KEYSTORE_PASSWORD.txt"

echo ===================================================================
echo         KALICI APK IMZASI - TEK SEFERLIK KURULUM
echo ===================================================================
echo  Bu islemden sonra yeni APK eskisinin uzerine "Guncelle" ile kurulur.
echo  Uygulamayi silip yeniden yuklemeniz gerekmez.
echo.
echo  GitHub'a 2 gizli deger (secret) eklenecek. Degerler bu klasordeki
echo  "imza" klasorunden okunur; depoya / internete acik yuklenmez.
echo ===================================================================
echo.

if not exist "%B64%" goto YOK
if not exist "%SIF%" goto YOK

where gh >nul 2>nul
if errorlevel 1 goto ELLE
gh auth status >nul 2>nul
if errorlevel 1 goto ELLE
echo GitHub CLI bulundu, secret'lar otomatik ekleniyor...
gh secret set ANDROID_KEYSTORE_BASE64 --repo %DEPO% < "%B64%"
if errorlevel 1 goto ELLE
gh secret set ANDROID_KEYSTORE_PASSWORD --repo %DEPO% < "%SIF%"
if errorlevel 1 goto ELLE
echo Iki secret da eklendi.
goto BITTI

:ELLE
echo Tarayicida GitHub'in "New repository secret" sayfasi acilacak.
echo Her adimda gereken metin PANOYA kopyalanir; siz sadece Ctrl+V yaparsiniz.
echo.
echo ------------------------- 1. SECRET -------------------------
echo|set /p="ANDROID_KEYSTORE_BASE64"|clip
start "" "%SAYFA%"
echo  [Panoda: ANDROID_KEYSTORE_BASE64]
echo  1) Acilan sayfada "Name" kutusuna Ctrl+V yapin.
echo     (GitHub giris isterse once giris yapin.)
echo  Hazir olunca bu pencerede bir tusa basin...
pause >nul
clip < "%B64%"
echo  [Panoda: imza anahtari - uzun bir metin]
echo  2) "Secret" kutusuna Ctrl+V yapin ve yesil "Add secret" dugmesine basin.
echo  Eklediyseniz bir tusa basin...
pause >nul
echo.
echo ------------------------- 2. SECRET -------------------------
echo|set /p="ANDROID_KEYSTORE_PASSWORD"|clip
start "" "%SAYFA%"
echo  [Panoda: ANDROID_KEYSTORE_PASSWORD]
echo  1) Yeni acilan sayfada "Name" kutusuna Ctrl+V yapin.
echo  Hazir olunca bir tusa basin...
pause >nul
clip < "%SIF%"
echo  [Panoda: imza sifresi]
echo  2) "Secret" kutusuna Ctrl+V yapin ve "Add secret" dugmesine basin.
echo  Eklediyseniz bir tusa basin...
pause >nul
echo.| clip
echo  (Pano temizlendi.)

:BITTI
echo.
echo ===================================================================
echo  TAMAM. Son bir kez yapilacaklar:
echo   1) Telefonlarda bekleyen (cevrimdisi) kayit olmadigindan emin olun.
echo   2) Simdi GitHub_Yukle.bat ile yeni APK'yi derletin.
echo   3) Telefondaki ESKI uygulamayi BIR KEZ silin, yeni APK'yi kurun.
echo      Bundan sonraki tum surumler silmeden "Guncelle" ile kurulur.
echo ===================================================================
choice /c EH /m "GitHub_Yukle.bat simdi calistirilsin mi"
if errorlevel 2 goto SON
call "%~dp0GitHub_Yukle.bat"
:SON
endlocal
exit /b 0

:YOK
echo HATA: "imza" klasoru veya icindeki dosyalar bulunamadi.
echo Bu dosya HaneButcesiV2 klasorunde, "imza" klasoruyle ayni yerde olmali.
pause
endlocal
exit /b 1
