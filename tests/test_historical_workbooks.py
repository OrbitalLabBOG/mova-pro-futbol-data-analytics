import io
import zipfile
import pytest
from experiments.data_ground_truth.historical_workbooks import inspect, literal_signature
from experiments.data_ground_truth.raw import select


def workbook(target='worksheets/sheet7.xml', formula=False, external=False):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Ordered by Popularity" sheetId="6" r:id="rId2"/></sheets></workbook>')
        mode=' TargetMode="External"' if external else ''
        z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships><Relationship Id="rId2" Target="{target}"{mode}/></Relationships>')
        f='<f>1+1</f>' if formula else ''
        z.writestr('xl/worksheets/sheet7.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="20"><c r="A20" t="inlineStr"><is><t>Player</t></is></c><c r="B20" t="inlineStr"><is><t>Club</t></is></c><c r="C20">'+f+'<v>99</v></c><c r="D20"><v>5.5</v></c><c r="E20" t="inlineStr"><is><t>MF</t></is></c></row></sheetData></worksheet>')
        z.writestr('xl/vbaProject.bin',b'unexecuted macro payload')
    return b.getvalue()


def test_sheet_relationship_and_formula_cache_are_preserved_without_evaluation():
    table=inspect(workbook(formula=True))[0]
    assert table['xml_path']=='xl/worksheets/sheet7.xml'
    assert table['metric']=='popularity_unresolved_snapshot'
    row=table['rows'][0]
    assert row['cells']['C']=={'address':'C20','value':'99','formula':'1+1'}
    assert literal_signature(row) is None
    assert literal_signature(inspect(workbook())[0]['rows'][0])==('Player','Club','99','5.5','MF')


def test_external_and_escaping_worksheet_relationships_are_rejected():
    for target,external in [('https://example.org/data',True),('../../outside.xml',False)]:
        with pytest.raises(ValueError):inspect(workbook(target=target,external=external))


def test_only_reviewed_official_workbooks_are_selected():
    repo='lifebeyondfife/FantasyFootball'
    assert select(repo,'Fantasy Football Team Selector 13-14.xlsm')
    assert not select(repo,'fantasy-football.vba')
    assert not select(repo,'Fantasy Football Team Selector Yahoo 2012-13/Fantasy Football Team Selector Yahoo 12-13.xlsm')
