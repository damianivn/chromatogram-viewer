"""Frozen FID batch requests; a failed sample prevents final PDF publication."""
from datetime import datetime, timezone
import json
from pathlib import Path

from gcviewer.services.fid_acquisition import run_record
from gcviewer.services.fid_workflow import AnalysisMethod, ANALYSIS_REVISION, LIMITATIONS, calculate, digest, report_range, typed_result
from gcviewer.reports.publication import fingerprint


def write_batch_request(folder, sources, method, layout):
    request = dict(sources=[dict(source=str(Path(path).resolve()), sha256=sha) for path, sha in sources],
                   method=method.to_dict(), layout=layout.to_dict())
    if not request['sources']:
        raise ValueError('Select at least one FID sample.')
    paths = [item['source'].casefold() for item in request['sources']]
    if len(paths) != len(set(paths)):
        raise ValueError('Select each acquisition only once.')
    (Path(folder)/'request.json').write_text(json.dumps(request, allow_nan=False), encoding='utf-8')
    return digest(request)


def execute_batch(folder):
    from gcviewer.services.acquisition import load_fid
    from gcviewer.reports.fid_pdf import ReportEntry, ReportOptions, write_report
    folder = Path(folder)
    request = json.loads((folder/'request.json').read_text(encoding='utf-8'))
    method = AnalysisMethod.from_dict(request['method'])
    options = ReportOptions.from_dict(request['layout'])
    rows, entries, records = [], [], []

    def progress(message):
        path = folder/'progress.tmp'
        path.write_text(json.dumps(dict(message=message, rows=rows)), encoding='utf-8')
        path.replace(folder/'progress.json')

    for index, source in enumerate(request['sources']):
        progress(f"Analysing {index+1} of {len(request['sources'])}: {Path(source['source']).name}")
        row = dict(source=source['source'], status='Failed', detail='')
        try:
            run = load_fid(source['source'])
            if run.sha256 != source['sha256']:
                raise ValueError('Acquisition changed since it was opened. Reopen it before reporting.')
            record = calculate(run, method)
            result = typed_result(record, run)
            report_range(run, result, options)
            notes = () if record['effective_delay_min'] is None else (
                f"Solvent excluded before {record['effective_delay_min']:.6g} min; area % uses included peaks.",)
            entries.append(ReportEntry(run, result, {int(k):v for k,v in record['names'].items()}, record['missing'], notes))
            records.append(dict(acquisition=run_record(run), analysis=record))
            row.update(status='Ready', detail=f"{len(record['peaks'])} peaks")
        except Exception as exc:
            row['detail'] = str(exc)
        rows.append(row)
    response = dict(request_key=digest(request), rows=rows, success=False)
    def recheck():
        for row, source in zip(rows, request['sources']):
            if row['status'] != 'Ready':
                continue
            try:
                if fingerprint(source['source']) != source['sha256']:
                    raise ValueError('Acquisition changed during batch reporting. Reopen it and retry.')
            except Exception as exc:
                row.update(status='Failed', detail=str(exc))
        return all(row['status'] == 'Ready' for row in rows)

    if not recheck():
        progress('No report created. Review the failed samples.')
        return response
    progress(f"Rendering report for {len(entries)} samples…")
    info = write_report(folder/'output.pdf', entries, options)
    if not recheck():
        (folder/'output.pdf').unlink(missing_ok=True)
        progress('A source changed. No report created.')
        return response
    metadata = dict(schema='gcviewer-fid-batch-export-v1', revision=ANALYSIS_REVISION,
                    generated_utc=datetime.now(timezone.utc).isoformat(), request_key=digest(request),
                    selected_count=len(rows), succeeded_count=len(rows), failed_count=0,
                    method=method.to_dict(), report_layout=options.to_dict(), samples=records,
                    limitations=LIMITATIONS, figure_processing_applied=False,
                    output_sha256=fingerprint(folder/'output.pdf'), report_pages=info.pages)
    (folder/'output.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    response.update(success=True, pages=info.pages)
    return response
