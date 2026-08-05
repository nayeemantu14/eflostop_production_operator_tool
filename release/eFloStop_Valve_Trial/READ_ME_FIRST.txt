===========================================================
 eFloStop II Production Tool — Valve Trial Assembly (10 boards)
===========================================================

WHAT IS IN THIS PACKAGE
-----------------------
  eFloStop_Production_Tool\   The application (do not split this folder up)
  Work Instruction\           WI-VALVE-001 — the step-by-step procedure
  READ_ME_FIRST.txt           This file


SETUP — DO THESE IN ORDER
-------------------------

1) UNZIP EVERYTHING FIRST
   Do not run the tool from inside the ZIP file. Extract the whole folder first.

2) PUT IT SOMEWHERE YOU CAN WRITE TO
   Good:  C:\eFloStop\   or your Desktop or Documents
   BAD:   C:\Program Files\   (the tool saves its records next to the .exe
          and cannot write there)

3) INSTALL STM32CubeProgrammer  ** REQUIRED — NOT INCLUDED **
   Download from STMicroelectronics and install to the DEFAULT location:
     C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\
   The tool calls STM32_Programmer_CLI.exe from that exact path.
   Nothing will flash without it.

4) INSTALL THE ST-LINK DRIVERS
   Plug in the ST-Link and confirm it appears in Windows Device Manager,
   including its Virtual COM Port (STMicroelectronics ... COMx).

5) TURN BLUETOOTH ON
   The PC needs a working Bluetooth 4.0+ (BLE) adapter, switched on.
   The tool talks to each board over Bluetooth to verify it.
   If Bluetooth is off, EVERY board fails even though flashing worked.


FIRST RUN
---------
Run:  eFloStop_Production_Tool\eFloStop_Production_Tool.exe

Windows may show a blue "Windows protected your PC" box because the
application is not code-signed. Click "More info" then "Run anyway".
If antivirus quarantines it, restore it / allow the folder.

The tool creates a "data" folder next to the .exe for its records.
Do not delete it — the batch records are exported from there at the end.


THEN
----
Follow the work instruction:
  Work Instruction\WI-VALVE-001_Valve_Programming.md

Read section 1.1 ("Read this first") before starting the first board.

Two things that catch people out:
  * Always select the ST-Link VCP COM port in the UART Port box.
    The tool refuses to start without it.
  * Only ONE valve board powered at a time, and the WiFi Hub powered down.


QUESTIONS
---------
Contact: ____________________
