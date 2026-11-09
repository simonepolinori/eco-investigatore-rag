@echo off
rem Gemini (chiave gratis da https://aistudio.google.com/apikey) scrive le risposte.
rem Potete anche incollarla una volta sola nell'interfaccia: pulsante Motori, "Salva e prova".
if "%GEMINI_API_KEY%"=="" set /p GEMINI_API_KEY=Incolla la chiave Gemini (AIza...) e premi Invio, oppure solo Invio se l'avete gia' salvata in ECO: 
python app.py
pause
