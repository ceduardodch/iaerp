"""Comprobantes SRI sintéticos usados por pruebas; no contienen datos reales."""

CREDIT_NOTE_RECEIVED_IVA15_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<autorizacion>
  <estado>AUTORIZADO</estado>
  <numeroAutorizacion>2111202504098888888800120010020000001111234567811</numeroAutorizacion>
  <fechaAutorizacion>2025-11-21T12:00:00-05:00</fechaAutorizacion>
  <comprobante><![CDATA[
    <notaCredito>
      <infoTributaria>
        <ruc>0888888888001</ruc><razonSocial>PROVEEDOR IVA DEMO</razonSocial>
        <codDoc>04</codDoc><estab>001</estab><ptoEmi>002</ptoEmi>
        <secuencial>000000111</secuencial>
        <claveAcceso>2111202504098888888800120010020000001111234567811</claveAcceso>
      </infoTributaria>
      <infoNotaCredito>
        <fechaEmision>21/11/2025</fechaEmision>
        <identificacionComprador>0777777777001</identificacionComprador>
        <razonSocialComprador>EMPRESA DEMO</razonSocialComprador>
        <codDocModificado>01</codDocModificado>
        <numDocModificado>001-002-000019877</numDocModificado>
        <fechaEmisionDocSustento>11/11/2025</fechaEmisionDocSustento>
        <totalSinImpuestos>5.00</totalSinImpuestos>
        <valorModificacion>5.75</valorModificacion>
        <moneda>DOLAR</moneda>
        <totalConImpuestos><totalImpuesto>
          <codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje>
          <baseImponible>5.00</baseImponible><tarifa>15.00</tarifa><valor>0.75</valor>
        </totalImpuesto></totalConImpuestos>
        <motivo>Devolucion parcial de la compra</motivo>
      </infoNotaCredito>
    </notaCredito>
  ]]></comprobante>
</autorizacion>
"""
