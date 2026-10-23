@echo off
rem Tarea semanal: datos de MT5 (o la copia local), prueba de todas las estrategias y PDF nuevo.
cd /d "%~dp0.."
python -W ignore -m laboratorio > laboratorio\ultima_corrida.txt 2>&1
