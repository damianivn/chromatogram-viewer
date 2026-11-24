# Using Chromatogram Viewer

## Start the app on Windows

If you have a packaged copy, keep the application folder together and open `ChromatogramViewer.exe`. To run from source, open Command Prompt in the project folder and run the following once, using the path to your 64-bit Python 3.12 installation.

```bat
setup_qt.bat "C:\Path\To\Python312\python.exe"
```

Double-click `launch_qt.vbs` to start the viewer. If startup fails, run `.venv-qt\Scripts\python.exe -m gcviewer.desktop` from the project folder to see the error.

## Open a chromatogram

Choose **File > Open**. For GC-MS, select the acquisition **folder** ending in `.raw`. For GC-FID, select one or more TotalChrom **files** ending in `.raw`. To match a TurboMass sample list to a data folder, choose **Sample library**, browse for the folder and the `.spl` list, then choose **Open selected**.

Click a sample in the left pane to see its chromatogram. Use the magnifying glass below the plot to zoom into a retention-time range and **Home** to restore the overview. To overlay traces or stack them vertically, open two or more samples and choose **Analysis > Compare samples**.

## Integrate GC-FID peaks

1. Select a completed FID run and choose **View > FID Analysis** (`Ctrl+2`).
2. Review the settings under **Method**, then click **Integrate**. Click a peak in the results table to inspect its boundaries. If the detector clipped, treat the reported height and area as lower bounds.
3. To assign names, use **Use detected peaks for Names** on a representative run and enter the component names at the detected retention times. Save the assignments and integration settings together under **Analysis > FID method and names > Save** to reuse them across runs.
4. Click **PDF report** for a printable report, or use **File > Export** to save the peak table. Choose **View > Figure** (`Ctrl+1`) to return to the chromatogram.

## Inspect GC-MS data and export a figure

Select a GC-MS run and choose **Analysis > GC-MS inspection / EIC**. Select the MS function, then inspect a spectrum at one scan or average scans over a retention-time interval. To see where a particular ion elutes, enter its mass-to-charge ratio and click **Update preview**. The extracted ion chromatogram uses the nearest recorded mass channel.

For a figure, use **Figure > Style** to set the publication size and **Figure > Axes** to adjust the plotted range. Choose **File > Export** to save the figure or its numerical data.
