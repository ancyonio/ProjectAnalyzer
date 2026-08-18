"""Static constants: TIBCO namespaces, activity->Spring mappings, type maps.

Ported from the original single-file analyzer, extended with search synonyms,
relationship direction semantics and risk weights used by the impact engine.
"""
import re
from typing import Dict

# TIBCO BW XML namespaces
NS = {
    'pd':   'http://xmlns.tibco.com/bw/process/2003',
    'xsd':  'http://www.w3.org/2001/XMLSchema',
    'xs':   'http://www.w3.org/2001/XMLSchema',
    'xsl':  'http://www.w3.org/1999/XSL/Transform',
    'wsdl': 'http://schemas.xmlsoap.org/wsdl/',
    'soap': 'http://schemas.xmlsoap.org/wsdl/soap/',
    'repo': 'http://www.tibco.com/xmlns/repo/types/2002',
}

# TIBCO BW6 / BusinessWorks Container Edition namespaces.
# A `.bwp` file is a BPEL 2.0 process carrying TIBCO extensions, so the
# vocabulary is completely different from BW5's `.process` format.
NS6 = {
    'bpws':     'http://docs.oasis-open.org/wsbpel/2.0/process/executable',
    'sca-bpel': 'http://docs.oasis-open.org/ns/opencsa/sca-bpel/200801',
    'tibex':    'http://www.tibco.com/bpel/2007/extensions',
    'bwext':    'http://www.tibco.com/bw/model/core/bwext',
    'scaext':   'http://www.tibco.com/xmlns/sca/2009/08',
    'xsd':      'http://www.w3.org/2001/XMLSchema',
    'xs':       'http://www.w3.org/2001/XMLSchema',
    'wsdl':     'http://schemas.xmlsoap.org/wsdl/',
    'xsi':      'http://www.w3.org/2001/XMLSchema-instance',
}

# ─────────────────────────────────────────────────────────────
# Activity Type → Spring Boot Mapping  (comprehensive)
# ─────────────────────────────────────────────────────────────
ACTIVITY_SPRING_MAP: Dict[str, Dict[str, str]] = {
    # HTTP
    'com.tibco.plugin.http.HTTPEventSource':           {'spring': '@RestController / @GetMapping', 'category': 'HTTP_RECEIVER'},
    'com.tibco.plugin.http.HTTPResponseActivity':      {'spring': 'ResponseEntity<>', 'category': 'HTTP_RESPONSE'},
    'com.tibco.plugin.http.client.HttpRequestActivity': {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    # SOAP
    'com.tibco.plugin.soap.SOAPEventSource':           {'spring': '@Endpoint (Spring WS)', 'category': 'SOAP_RECEIVER'},
    'com.tibco.plugin.soap.SOAPSendReceiveActivity':   {'spring': 'WebServiceTemplate', 'category': 'SOAP_CALL'},
    'com.tibco.plugin.soap.SOAPSendFaultActivity':     {'spring': 'SoapFaultException', 'category': 'SOAP_FAULT'},
    # JMS
    'com.tibco.plugin.jms.JMSQueueEventSource':        {'spring': '@JmsListener', 'category': 'JMS_RECEIVER'},
    'com.tibco.plugin.jms.JMSQueueSendActivity':       {'spring': 'JmsTemplate.send()', 'category': 'JMS_SEND'},
    'com.tibco.plugin.jms.JMSTopicPublishActivity':    {'spring': 'JmsTemplate.convertAndSend()', 'category': 'JMS_PUBLISH'},
    'com.tibco.plugin.jms.JMSTopicSubscribeActivity':  {'spring': '@JmsListener (topic)', 'category': 'JMS_SUBSCRIBE'},
    'com.tibco.plugin.jms.JMSQueueRequestReplyActivity': {'spring': 'JmsTemplate.sendAndReceive()', 'category': 'JMS_REQUEST_REPLY'},
    # JDBC
    'com.tibco.plugin.jdbc.JDBCQueryActivity':         {'spring': 'JdbcTemplate.query()', 'category': 'JDBC_QUERY'},
    'com.tibco.plugin.jdbc.JDBCUpdateActivity':        {'spring': 'JdbcTemplate.update()', 'category': 'JDBC_UPDATE'},
    'com.tibco.plugin.jdbc.JDBCCallProcedure':         {'spring': 'SimpleJdbcCall', 'category': 'JDBC_STORED_PROC'},
    'com.tibco.plugin.jdbc.JDBCGeneralActivity':       {'spring': 'JdbcTemplate', 'category': 'JDBC_GENERAL'},
    # File
    'com.tibco.plugin.file.FileReadActivity':          {'spring': 'Files.readAllBytes()', 'category': 'FILE_READ'},
    'com.tibco.plugin.file.FileWriteActivity':         {'spring': 'Files.write()', 'category': 'FILE_WRITE'},
    'com.tibco.plugin.file.FilePollerActivity':        {'spring': '@Scheduled / WatchService', 'category': 'FILE_POLLER'},
    'com.tibco.plugin.file.FileCopyActivity':          {'spring': 'Files.copy()', 'category': 'FILE_COPY'},
    'com.tibco.plugin.file.FileRemoveActivity':        {'spring': 'Files.delete()', 'category': 'FILE_DELETE'},
    'com.tibco.plugin.file.FileRenameActivity':        {'spring': 'Files.move()', 'category': 'FILE_RENAME'},
    'com.tibco.plugin.file.FileListActivity':          {'spring': 'Files.list()', 'category': 'FILE_LIST'},
    # XML / Data
    'com.tibco.plugin.xml.XMLParseActivity':           {'spring': 'JAXB Unmarshaller', 'category': 'XML_PARSE'},
    'com.tibco.plugin.xml.XMLRenderActivity':          {'spring': 'JAXB Marshaller', 'category': 'XML_RENDER'},
    'com.tibco.plugin.xml.XMLTransformActivity':       {'spring': 'javax.xml.transform.Transformer', 'category': 'XSLT_TRANSFORM'},
    'com.tibco.plugin.json.JSONParseActivity':         {'spring': 'ObjectMapper.readValue()', 'category': 'JSON_PARSE'},
    'com.tibco.plugin.json.JSONRenderActivity':        {'spring': 'ObjectMapper.writeValueAsString()', 'category': 'JSON_RENDER'},
    'com.tibco.plugin.parse.ParseDataActivity':        {'spring': 'Custom Parser (CSV / Fixed)', 'category': 'PARSE_DATA'},
    'com.tibco.plugin.parse.RenderDataActivity':       {'spring': 'Custom Renderer', 'category': 'RENDER_DATA'},
    # Mapper
    'com.tibco.plugin.mapper.MapperActivity':          {'spring': 'MapStruct / ModelMapper', 'category': 'MAPPER'},
    # Core / Control flow
    'com.tibco.pe.core.CallProcessActivity':           {'spring': '@Autowired + service.method()', 'category': 'CALL_PROCESS'},
    'com.tibco.pe.core.WriteToLogActivity':            {'spring': 'Logger.info() / Logger.error()', 'category': 'LOG'},
    'com.tibco.pe.core.GenerateErrorActivity':         {'spring': 'throw new RuntimeException()', 'category': 'GENERATE_ERROR'},
    'com.tibco.pe.core.CatchActivity':                 {'spring': '@ExceptionHandler / try-catch', 'category': 'CATCH'},
    'com.tibco.pe.core.RethrowActivity':               {'spring': 'throw e', 'category': 'RETHROW'},
    'com.tibco.pe.core.ConfirmActivity':               {'spring': 'Transaction commit', 'category': 'CONFIRM'},
    'com.tibco.pe.core.SetSharedVariableActivity':     {'spring': '@Cacheable / Redis', 'category': 'SET_SHARED_VAR'},
    'com.tibco.pe.core.GetSharedVariableActivity':     {'spring': '@Cacheable / Redis', 'category': 'GET_SHARED_VAR'},
    'com.tibco.pe.core.EngineCommandActivity':         {'spring': 'ApplicationContext / Actuator', 'category': 'ENGINE_COMMAND'},
    'com.tibco.pe.core.InferSchemaActivity':           {'spring': 'Reflection / Schema util', 'category': 'INFER_SCHEMA'},
    # Timer
    'com.tibco.plugin.timer.TimerEventSource':         {'spring': '@Scheduled', 'category': 'TIMER'},
    'com.tibco.plugin.timer.NullActivity':             {'spring': '// no-op (control flow)', 'category': 'NULL_ACTIVITY'},
    'com.tibco.plugin.timer.SleepActivity':            {'spring': 'Thread.sleep() / @Async', 'category': 'SLEEP'},
    # RV (Rendezvous)
    'com.tibco.plugin.tibrv.RVPubActivity':            {'spring': 'JmsTemplate (migrated from RV)', 'category': 'RV_PUBLISH'},
    'com.tibco.plugin.tibrv.RVSubActivity':            {'spring': '@JmsListener (migrated from RV)', 'category': 'RV_SUBSCRIBE'},
    # FTP
    'com.tibco.plugin.ftp.FTPPutActivity':             {'spring': 'Spring Integration FTP', 'category': 'FTP_PUT'},
    'com.tibco.plugin.ftp.FTPGetActivity':             {'spring': 'Spring Integration FTP', 'category': 'FTP_GET'},
    # Mail
    'com.tibco.plugin.mail.MailSendActivity':          {'spring': 'JavaMailSender', 'category': 'MAIL_SEND'},
    # Java / General
    'com.tibco.plugin.java.JavaActivity':              {'spring': 'Native Java class', 'category': 'JAVA_ACTIVITY'},
    'com.tibco.pe.core.AssignActivity':                {'spring': 'Variable assignment', 'category': 'ASSIGN'},
}

# ─────────────────────────────────────────────────────────────
# BW6 / BWCE activity mapping.
#
# BW6 identifies an activity by `activityTypeID` on the `bwext:BWActivity`
# element (or by the BPEL element name for native constructs), not by the
# Java class name BW5 used. Categories are deliberately the SAME strings as
# ACTIVITY_SPRING_MAP so entry-point detection, the integration surface,
# diagrams and reports work identically across BW5 and BW6 estates.
# ─────────────────────────────────────────────────────────────
BW6_ACTIVITY_MAP: Dict[str, Dict[str, str]] = {
    # HTTP / REST
    'bw.http.receiveRequest':        {'spring': '@RestController / @GetMapping', 'category': 'HTTP_RECEIVER'},
    'bw.http.sendHTTPRequest':       {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'bw.http.sendHTTPResponse':      {'spring': 'ResponseEntity<>', 'category': 'HTTP_RESPONSE'},
    'bw.http.waitForHTTPRequest':    {'spring': '@RestController (async)', 'category': 'HTTP_RECEIVER'},
    'bw.restjson.RestInvokeActivity':   {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'bw.restjson.RestResponseActivity': {'spring': 'ResponseEntity<>', 'category': 'HTTP_RESPONSE'},
    'bw.generalactivities.confirm':     {'spring': 'Transaction commit', 'category': 'CONFIRM'},
    'bw.generalactivities.checkpoint':  {'spring': 'Persist job state', 'category': 'CHECKPOINT'},
    'bw.restjson.jsontoxml':         {'spring': 'ObjectMapper.readValue()', 'category': 'JSON_PARSE'},
    'bw.restjson.xmltojson':         {'spring': 'ObjectMapper.writeValueAsString()', 'category': 'JSON_RENDER'},
    # SOAP
    'bw.soap.sendrequest':           {'spring': 'WebServiceTemplate', 'category': 'SOAP_CALL'},
    'bw.soap.receiverequest':        {'spring': '@Endpoint (Spring WS)', 'category': 'SOAP_RECEIVER'},
    'bw.soap.sendreply':             {'spring': '@ResponsePayload', 'category': 'SOAP_RESPONSE'},
    'bw.soap.sendfault':             {'spring': 'SoapFaultException', 'category': 'SOAP_FAULT'},
    # JMS
    'bw.jms.SendMessage':            {'spring': 'JmsTemplate.send()', 'category': 'JMS_SEND'},
    'bw.jms.ReceiveMessage':         {'spring': '@JmsListener', 'category': 'JMS_RECEIVER'},
    'bw.jms.GetMessage':             {'spring': 'JmsTemplate.receive()', 'category': 'JMS_RECEIVER'},
    'bw.jms.ReplyToMessage':         {'spring': 'JmsTemplate.send() (reply)', 'category': 'JMS_SEND'},
    'bw.jms.RequestReply':           {'spring': 'JmsTemplate.sendAndReceive()', 'category': 'JMS_REQUEST_REPLY'},
    'bw.jms.WaitForJMSRequest':      {'spring': '@JmsListener (topic)', 'category': 'JMS_SUBSCRIBE'},
    # JDBC
    'bw.jdbc.query':                 {'spring': 'JdbcTemplate.query()', 'category': 'JDBC_QUERY'},
    'bw.jdbc.update':                {'spring': 'JdbcTemplate.update()', 'category': 'JDBC_UPDATE'},
    'bw.jdbc.call':                  {'spring': 'SimpleJdbcCall', 'category': 'JDBC_STORED_PROC'},
    'bw.jdbc.jdbcgeneralactivity':   {'spring': 'JdbcTemplate', 'category': 'JDBC_GENERAL'},
    # File
    'bw.file.read':                  {'spring': 'Files.readAllBytes()', 'category': 'FILE_READ'},
    'bw.file.write':                 {'spring': 'Files.write()', 'category': 'FILE_WRITE'},
    'bw.file.copy':                  {'spring': 'Files.copy()', 'category': 'FILE_COPY'},
    'bw.file.remove':                {'spring': 'Files.delete()', 'category': 'FILE_DELETE'},
    'bw.file.rename':                {'spring': 'Files.move()', 'category': 'FILE_RENAME'},
    'bw.file.list':                  {'spring': 'Files.list()', 'category': 'FILE_LIST'},
    'bw.file.poller':                {'spring': '@Scheduled / WatchService', 'category': 'FILE_POLLER'},
    # XML / data
    'bw.xml.parsexml':               {'spring': 'JAXB Unmarshaller', 'category': 'XML_PARSE'},
    'bw.xml.renderxml':              {'spring': 'JAXB Marshaller', 'category': 'XML_RENDER'},
    'bw.xml.transformxml':           {'spring': 'javax.xml.transform.Transformer', 'category': 'XSLT_TRANSFORM'},
    'bw.parse.parsedata':            {'spring': 'Custom Parser (CSV / Fixed)', 'category': 'PARSE_DATA'},
    'bw.parse.renderdata':           {'spring': 'Custom Renderer', 'category': 'RENDER_DATA'},
    # General
    'bw.generalactivities.mapper':   {'spring': 'MapStruct / ModelMapper', 'category': 'MAPPER'},
    'bw.generalactivities.log':      {'spring': 'Logger.info() / Logger.error()', 'category': 'LOG'},
    'bw.generalactivities.null':     {'spring': '// no-op (control flow)', 'category': 'NULL_ACTIVITY'},
    'bw.generalactivities.sleep':    {'spring': 'Thread.sleep() / @Async', 'category': 'SLEEP'},
    'bw.generalactivities.timer':    {'spring': '@Scheduled', 'category': 'TIMER'},
    'bw.internal.callprocess':       {'spring': '@Autowired + service.method()', 'category': 'CALL_PROCESS'},
    'bw.internal.jobqueue':          {'spring': 'TaskExecutor', 'category': 'JOB_QUEUE'},
    # Error handling
    'bw.generalactivities.throw':    {'spring': 'throw new RuntimeException()', 'category': 'GENERATE_ERROR'},
    'bw.generalactivities.rethrow':  {'spring': 'throw e', 'category': 'RETHROW'},
    'bw.generalactivities.catch':    {'spring': '@ExceptionHandler / try-catch', 'category': 'CATCH'},
    # FTP / mail
    'bw.ftp.put':                    {'spring': 'Spring Integration FTP', 'category': 'FTP_PUT'},
    'bw.ftp.get':                    {'spring': 'Spring Integration FTP', 'category': 'FTP_GET'},
    'bw.mail.sendmail':              {'spring': 'JavaMailSender', 'category': 'MAIL_SEND'},
    # Java
    'bw.java.invoke':                {'spring': 'Native Java class', 'category': 'JAVA_ACTIVITY'},
    'bw.java.javainvoke':            {'spring': 'Native Java class', 'category': 'JAVA_ACTIVITY'},
    # -------------------------------------------------------------
    # Lower-case ids as BW6/BWCE actually emits them. The entries above use the
    # BW5-era CamelCase spelling; BW6 writes `bw.jms.receive`, and without these
    # the plugin-family fallback classified receivers as senders, which removed
    # them from the entry-point set.
    # -------------------------------------------------------------
    'bw.jms.receive':                {'spring': '@JmsListener', 'category': 'JMS_RECEIVER'},
    'bw.jms.get':                    {'spring': 'JmsTemplate.receive()', 'category': 'JMS_RECEIVER'},
    'bw.jms.signalin':               {'spring': '@JmsListener (wait for message)', 'category': 'JMS_RECEIVER'},
    'bw.jms.subscribe':              {'spring': '@JmsListener (topic)', 'category': 'JMS_SUBSCRIBE'},
    'bw.jms.send':                   {'spring': 'JmsTemplate.send()', 'category': 'JMS_SEND'},
    'bw.jms.publish':                {'spring': 'JmsTemplate.convertAndSend()', 'category': 'JMS_PUBLISH'},
    'bw.jms.reply':                  {'spring': 'JmsTemplate.send() (reply)', 'category': 'JMS_SEND'},
    'bw.jms.requestreply':           {'spring': 'JmsTemplate.sendAndReceive()', 'category': 'JMS_REQUEST_REPLY'},
    'bw.http.HTTPReceiver':          {'spring': 'Spring @RestController', 'category': 'HTTP_RECEIVER'},
    'bw.http.receiver':              {'spring': 'Spring @RestController', 'category': 'HTTP_RECEIVER'},
    'bw.http.sendHTTPRequest':       {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'bw.jdbc.JDBCQuery':             {'spring': 'JdbcTemplate.query()', 'category': 'JDBC_QUERY'},
    'bw.jdbc.query':                 {'spring': 'JdbcTemplate.query()', 'category': 'JDBC_QUERY'},
    'bw.jdbc.SQLDirect':             {'spring': 'JdbcTemplate.execute()', 'category': 'JDBC_GENERAL'},
    'bw.jdbc.calProcedure':          {'spring': 'SimpleJdbcCall', 'category': 'JDBC_STORED_PROC'},
    'bw.restjson.JsonParser':        {'spring': 'Jackson ObjectMapper.readValue()', 'category': 'JSON_PARSE'},
    'bw.restjson.JsonRender':        {'spring': 'Jackson ObjectMapper.writeValue()', 'category': 'JSON_RENDER'},
    'bw.restjson.Rest':              {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'bw.mail.send':                  {'spring': 'JavaMailSender', 'category': 'MAIL_SEND'},
    'bw.internal.end':               {'spring': '// end of process', 'category': 'INTERNAL'},
    'bw.internal.accumulateend':     {'spring': '// end of iteration', 'category': 'INTERNAL'},
    'bw.internal.start':             {'spring': '// start of process', 'category': 'INTERNAL'},
}

# Native BPEL constructs that carry meaning even without a TIBCO extension.
# A `receive` with createInstance="yes" is what makes a BW6 process an entry point.
# ─────────────────────────────────────────────────────────────
# BW6/BWCE ships a long tail of plugins (Kafka, MongoDB, S3, SAP,
# Salesforce, …) and each release adds more. Rather than pretend to
# enumerate every activityTypeID, an unknown `bw.<plugin>.<op>` id falls back
# to its plugin family, so a new plugin is categorised as messaging or
# database work instead of vanishing into CUSTOM.
# ─────────────────────────────────────────────────────────────
BW6_PLUGIN_FAMILIES: Dict[str, Dict[str, str]] = {
    'http':      {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'restjson':  {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'rest':      {'spring': 'RestTemplate / WebClient', 'category': 'HTTP_REQUEST'},
    'soap':      {'spring': 'WebServiceTemplate', 'category': 'SOAP_CALL'},
    'jdbc':      {'spring': 'JdbcTemplate', 'category': 'JDBC_GENERAL'},
    'jms':       {'spring': 'JmsTemplate', 'category': 'JMS_SEND'},
    'kafka':     {'spring': 'KafkaTemplate / @KafkaListener', 'category': 'KAFKA'},
    'tibrv':     {'spring': 'JmsTemplate (migrated from RV)', 'category': 'RV_PUBLISH'},
    'file':      {'spring': 'java.nio.file.Files', 'category': 'FILE_GENERAL'},
    'ftp':       {'spring': 'Spring Integration FTP', 'category': 'FTP_GET'},
    'sftp':      {'spring': 'Spring Integration SFTP', 'category': 'FTP_GET'},
    'mail':      {'spring': 'JavaMailSender', 'category': 'MAIL_SEND'},
    'mongodb':   {'spring': 'MongoTemplate', 'category': 'NOSQL'},
    'cassandra': {'spring': 'CassandraTemplate', 'category': 'NOSQL'},
    'redis':     {'spring': 'RedisTemplate', 'category': 'CACHE'},
    's3':        {'spring': 'AWS SDK S3Client', 'category': 'OBJECT_STORE'},
    'sqs':       {'spring': 'AWS SDK SqsClient', 'category': 'CLOUD_QUEUE'},
    'sns':       {'spring': 'AWS SDK SnsClient', 'category': 'CLOUD_TOPIC'},
    'salesforce': {'spring': 'Salesforce REST client', 'category': 'SAAS_CALL'},
    'sap':       {'spring': 'SAP JCo connector', 'category': 'ERP_CALL'},
    'java':      {'spring': 'Native Java class', 'category': 'JAVA_ACTIVITY'},
    'xml':       {'spring': 'JAXB / Transformer', 'category': 'XML_GENERAL'},
    'parse':     {'spring': 'Custom Parser', 'category': 'PARSE_DATA'},
    'internal':  {'spring': 'Internal control flow', 'category': 'INTERNAL'},
    'generalactivities': {'spring': 'Utility step', 'category': 'GENERAL'},
}


# Operation-name fragments that mean "this activity waits for something to
# arrive" rather than "this activity sends something out".
INBOUND_OPERATION_TOKENS = ('receive', 'subscribe', 'signalin', 'waitfor',
                            'poller', 'listen', 'consume')
# Matched as a prefix only: 'get' as a substring would also hit 'target'.
INBOUND_OPERATION_PREFIXES = ('get',)

# Where a plugin family has a distinct inbound form, name it: an unmapped
# inbound activity is an entry point and must not be reported as an outbound
# call.
BW6_INBOUND_OPERATIONS: Dict[str, Dict[str, str]] = {
    'jms':      {'spring': '@JmsListener', 'category': 'JMS_RECEIVER'},
    'kafka':    {'spring': '@KafkaListener', 'category': 'KAFKA'},
    'tibrv':    {'spring': '@JmsListener (migrated from RV)', 'category': 'RV_SUBSCRIBE'},
    'http':     {'spring': 'Spring @RestController', 'category': 'HTTP_RECEIVER'},
    'soap':     {'spring': 'Spring WS @Endpoint', 'category': 'SOAP_RECEIVER'},
    'file':     {'spring': 'Spring Integration / WatchService', 'category': 'FILE_POLLER'},
}


def bw6_activity_mapping(type_id: str) -> Dict[str, str]:
    """Resolve a BW6 `activityTypeID` to a category and Spring target.

    Exact id first, then the plugin family from `bw.<plugin>.<op>`, then
    CUSTOM. Returning a family match keeps an unrecognised plugin visible in
    the integration surface rather than silently uncategorised.
    """
    if not type_id:
        return {'spring': 'Manual Implementation', 'category': 'CUSTOM'}
    exact = BW6_ACTIVITY_MAP.get(type_id)
    if exact:
        return exact
    parts = type_id.split('.')
    if len(parts) >= 2 and parts[0] == 'bw':
        family = BW6_PLUGIN_FAMILIES.get(parts[1])
        if family:
            # A family default has to pick a direction, and picking "send" for
            # an unknown receive-side activity hides an entry point. Read the
            # operation half of the id before falling back to the default.
            operation = '.'.join(parts[2:]).lower()
            inbound = BW6_INBOUND_OPERATIONS.get(parts[1])
            if inbound and (any(token in operation for token in INBOUND_OPERATION_TOKENS)
                            or operation.startswith(INBOUND_OPERATION_PREFIXES)):
                return inbound
            return {'spring': family['spring'], 'category': family['category']}
    return {'spring': 'Manual Implementation', 'category': 'CUSTOM'}


BPEL_ACTIVITY_MAP: Dict[str, Dict[str, str]] = {
    'receive':    {'spring': '@RestController / @JmsListener', 'category': 'BPEL_RECEIVE'},
    'reply':      {'spring': 'ResponseEntity<>', 'category': 'BPEL_REPLY'},
    'invoke':     {'spring': 'service.method() / WebClient', 'category': 'BPEL_INVOKE'},
    'assign':     {'spring': 'Variable assignment', 'category': 'ASSIGN'},
    'throw':      {'spring': 'throw new RuntimeException()', 'category': 'GENERATE_ERROR'},
    'rethrow':    {'spring': 'throw e', 'category': 'RETHROW'},
    'wait':       {'spring': 'Thread.sleep() / @Async', 'category': 'SLEEP'},
    'empty':      {'spring': '// no-op (control flow)', 'category': 'NULL_ACTIVITY'},
    'exit':       {'spring': 'return', 'category': 'EXIT'},
    'compensate': {'spring': 'Compensating transaction', 'category': 'COMPENSATE'},
}

# BPEL structured activities: containers, not work. Recorded as Group nodes.
BPEL_STRUCTURED = {
    'sequence', 'flow', 'if', 'else', 'elseif', 'while', 'repeatUntil',
    'forEach', 'pick', 'scope',
}

# XSD → Java type mapping
XSD_JAVA_TYPE_MAP = {
    'string': 'String', 'normalizedString': 'String', 'token': 'String',
    'int': 'Integer', 'integer': 'java.math.BigInteger',
    'long': 'Long', 'short': 'Short', 'byte': 'Byte',
    'unsignedInt': 'Long', 'unsignedLong': 'java.math.BigInteger',
    'unsignedShort': 'Integer', 'unsignedByte': 'Short',
    'positiveInteger': 'java.math.BigInteger', 'negativeInteger': 'java.math.BigInteger',
    'nonPositiveInteger': 'java.math.BigInteger', 'nonNegativeInteger': 'java.math.BigInteger',
    'boolean': 'Boolean',
    'decimal': 'java.math.BigDecimal',
    'float': 'Float', 'double': 'Double',
    'dateTime': 'java.time.LocalDateTime', 'date': 'java.time.LocalDate',
    'time': 'java.time.LocalTime', 'duration': 'java.time.Duration',
    'gYear': 'javax.xml.datatype.XMLGregorianCalendar',
    'gMonth': 'javax.xml.datatype.XMLGregorianCalendar',
    'gDay': 'javax.xml.datatype.XMLGregorianCalendar',
    'base64Binary': 'byte[]', 'hexBinary': 'byte[]',
    'anyURI': 'java.net.URI', 'QName': 'javax.xml.namespace.QName',
    'NOTATION': 'javax.xml.namespace.QName',
    'anyType': 'Object', 'anySimpleType': 'Object',
}

# -------------------------------------------------------------
# Shared resource type detection
#
# BW5 and BW6/BWCE name shared resources completely differently: BW5 uses
# '.sharedjdbc' and friends, BW6 uses '.jdbcResource' and friends wrapped in an
# XMI 'jndi:namedResource' envelope. Both generations are listed here. The
# parser also falls back to the resource's own '@type' attribute for any BW6
# resource whose extension is not yet catalogued, so an unknown BW6 resource
# degrades to a typed node instead of disappearing from the graph.
# -------------------------------------------------------------
SHARED_RESOURCE_MAP_BW5 = {
    '.sharedhttp':    {'type': 'HTTP_CONNECTION',  'tech': 'HTTP',  'spring': 'RestTemplate / WebClient'},
    '.sharedjmscon':  {'type': 'JMS_CONNECTION',   'tech': 'JMS',   'spring': 'JmsTemplate / @JmsListener'},
    '.sharedjdbc':    {'type': 'JDBC_CONNECTION',  'tech': 'JDBC',  'spring': 'DataSource / JdbcTemplate'},
    '.sharedjmsapp':  {'type': 'JMS_APP_PROPS',    'tech': 'JMS',   'spring': 'JMS Message Properties'},
    '.sharedvariable':{'type': 'SHARED_VARIABLE',  'tech': 'Cache', 'spring': 'Spring Cache / Redis'},
    '.httpProxy':     {'type': 'HTTP_PROXY',       'tech': 'HTTP',  'spring': 'Proxy Configuration'},
    '.rvtransport':   {'type': 'RV_TRANSPORT',     'tech': 'RV',    'spring': 'JmsTemplate (migrated)'},
    '.sharedparse':   {'type': 'PARSE_CONFIG',     'tech': 'Parse', 'spring': 'Custom Parser Config'},
    '.sharednotify':  {'type': 'NOTIFICATION',     'tech': 'Event', 'spring': 'ApplicationEventPublisher'},
    '.sharedLock':    {'type': 'LOCK',             'tech': 'Sync',  'spring': 'ReentrantLock / @Synchronized'},
    '.id':            {'type': 'IDENTITY',         'tech': 'Auth',  'spring': 'Spring Security Credentials'},
}

# BW6 / BWCE shared resources. Extensions are matched case-insensitively by the
# parser, so the canonical TIBCO spelling is used here for readability.
SHARED_RESOURCE_MAP_BW6 = {
    '.jdbcResource':        {'type': 'JDBC_CONNECTION',  'tech': 'JDBC',  'spring': 'DataSource / JdbcTemplate'},
    '.jmsConnResource':     {'type': 'JMS_CONNECTION',   'tech': 'JMS',   'spring': 'JmsTemplate / @JmsListener'},
    '.jndiConfigResource':  {'type': 'JNDI_CONFIG',      'tech': 'JNDI',  'spring': 'JndiTemplate'},
    '.httpConnResource':    {'type': 'HTTP_CONNECTOR',   'tech': 'HTTP',  'spring': 'Embedded servlet container (server.port)'},
    '.httpClientResource':  {'type': 'HTTP_CLIENT',      'tech': 'HTTP',  'spring': 'RestTemplate / WebClient'},
    '.smtpResource':        {'type': 'SMTP',             'tech': 'Mail',  'spring': 'JavaMailSender'},
    '.dataformatresource':  {'type': 'DATA_FORMAT',      'tech': 'Parse', 'spring': 'Custom Parser Config'},
    '.ftpResource':         {'type': 'FTP',              'tech': 'FTP',   'spring': 'Spring Integration FTP'},
    '.javaGlobalInstance':  {'type': 'JAVA_INSTANCE',    'tech': 'Java',  'spring': '@Bean singleton'},
    '.sslClientResource':   {'type': 'SSL_CLIENT',       'tech': 'TLS',   'spring': 'TLS client configuration'},
    '.sslServerResource':   {'type': 'SSL_SERVER',       'tech': 'TLS',   'spring': 'TLS server configuration'},
    '.identityResource':    {'type': 'IDENTITY',         'tech': 'Auth',  'spring': 'Spring Security Credentials'},
    '.tcpResource':         {'type': 'TCP_CONNECTION',   'tech': 'TCP',   'spring': 'Socket / Netty channel'},
    '.ldapResource':        {'type': 'LDAP',             'tech': 'LDAP',  'spring': 'Spring LDAP'},
    '.kafkaResource':       {'type': 'KAFKA_CONNECTION', 'tech': 'Kafka', 'spring': 'KafkaTemplate / @KafkaListener'},
    '.proxyResource':       {'type': 'HTTP_PROXY',       'tech': 'HTTP',  'spring': 'Proxy Configuration'},
}

# 'jndi:namedResource/@type' prefix -> classification, used when a BW6 resource
# carries an extension that is not in the map above.
BW6_RESOURCE_TYPE_PREFIXES = {
    'jdbc':          {'type': 'JDBC_CONNECTION',  'tech': 'JDBC',  'spring': 'DataSource / JdbcTemplate'},
    'jms':           {'type': 'JMS_CONNECTION',   'tech': 'JMS',   'spring': 'JmsTemplate / @JmsListener'},
    'httpconnector': {'type': 'HTTP_CONNECTOR',   'tech': 'HTTP',  'spring': 'Embedded servlet container (server.port)'},
    'http':          {'type': 'HTTP_CLIENT',      'tech': 'HTTP',  'spring': 'RestTemplate / WebClient'},
    'smtp':          {'type': 'SMTP',             'tech': 'Mail',  'spring': 'JavaMailSender'},
    'dataformat':    {'type': 'DATA_FORMAT',      'tech': 'Parse', 'spring': 'Custom Parser Config'},
    'ftp':           {'type': 'FTP',              'tech': 'FTP',   'spring': 'Spring Integration FTP'},
    'ldap':          {'type': 'LDAP',             'tech': 'LDAP',  'spring': 'Spring LDAP'},
    'tcp':           {'type': 'TCP_CONNECTION',   'tech': 'TCP',   'spring': 'Socket / Netty channel'},
    'kafka':         {'type': 'KAFKA_CONNECTION', 'tech': 'Kafka', 'spring': 'KafkaTemplate / @KafkaListener'},
    'subject':       {'type': 'IDENTITY',         'tech': 'Auth',  'spring': 'Spring Security Credentials'},
    'java':          {'type': 'JAVA_INSTANCE',    'tech': 'Java',  'spring': '@Bean singleton'},
}

# Every shared-resource extension the analyzer knows about, both generations.
SHARED_RESOURCE_MAP = dict(SHARED_RESOURCE_MAP_BW5)
SHARED_RESOURCE_MAP.update(SHARED_RESOURCE_MAP_BW6)

# Connection-style resources that also get an 'Adapter' node wired to a 'System'.
ADAPTER_RESOURCE_TYPES = {
    'HTTP_CONNECTION', 'JMS_CONNECTION', 'JDBC_CONNECTION', 'RV_TRANSPORT',
    'HTTP_CONNECTOR', 'HTTP_CLIENT', 'SMTP', 'FTP', 'TCP_CONNECTION',
    'LDAP', 'KAFKA_CONNECTION', 'JNDI_CONFIG',
}

# ─────────────────────────────────────────────────────────────
# File type → artifact family (used for discovery statistics)
# ─────────────────────────────────────────────────────────────
ARTIFACT_FAMILIES: Dict[str, str] = {
    '.process': 'BW Process (BW5)',
    '.bwp': 'BW Process (BW6/CE)',
    '.xsd': 'XML Schema',
    '.wsdl': 'Service Contract',
    '.xsl': 'XSLT Transformation',
    '.xslt': 'XSLT Transformation',
    '.substvar': 'Global Variables',
    '.aeschema': 'AE Schema',
    '.sharedhttp': 'Shared Resource',
    '.sharedjmscon': 'Shared Resource',
    '.sharedjdbc': 'Shared Resource',
    '.sharedjmsapp': 'Shared Resource',
    '.sharedvariable': 'Shared Resource',
    '.httpProxy': 'Shared Resource',
    '.rvtransport': 'Shared Resource',
    '.sharedparse': 'Shared Resource',
    '.sharednotify': 'Shared Resource',
    '.sharedLock': 'Shared Resource',
    '.id': 'Shared Resource',
    '.jdbcResource': 'Shared Resource',
    '.jmsConnResource': 'Shared Resource',
    '.jndiConfigResource': 'Shared Resource',
    '.httpConnResource': 'Shared Resource',
    '.httpClientResource': 'Shared Resource',
    '.smtpResource': 'Shared Resource',
    '.dataformatresource': 'Shared Resource',
    '.ftpResource': 'Shared Resource',
    '.javaGlobalInstance': 'Shared Resource',
    '.sslClientResource': 'Shared Resource',
    '.sslServerResource': 'Shared Resource',
    '.identityResource': 'Shared Resource',
    '.tcpResource': 'Shared Resource',
    '.ldapResource': 'Shared Resource',
    '.kafkaResource': 'Shared Resource',
    '.proxyResource': 'Shared Resource',
    '.java': 'Java Source (not modelled)',
    '.policy': 'Policy (not modelled)',
    '.authxml': 'Policy (not modelled)',
    '.bwm': 'BW Module Descriptor',
    '.jar': 'Java Library',
    '.sql': 'SQL Script',
    '.json': 'Config / Service Descriptor',
    '.properties': 'Config',
}

# File types that are direct inputs to a graph parser. Keep this separate from
# ARTIFACT_FAMILIES, which also classifies intentionally unmodelled estate files
# such as Java sources and deployment descriptors.
PARSED_ARTIFACT_EXTENSIONS = {
    '.process', '.bwp', '.xsd', '.wsdl', '.xsl', '.xslt', '.substvar',
    '.aeschema',
    *(ext.lower() for ext in SHARED_RESOURCE_MAP),
}

# ─────────────────────────────────────────────────────────────
# Entry point categories: a BWProcess owning one of these is a
# runtime entry point (an externally reachable surface).
# ─────────────────────────────────────────────────────────────
ENTRY_POINT_CATEGORIES = {
    'HTTP_RECEIVER': 'REST/HTTP endpoint  -> Spring @RestController',
    'SOAP_RECEIVER': 'SOAP service        -> Spring WS @Endpoint',
    'JMS_RECEIVER':  'JMS queue consumer  -> @JmsListener',
    'JMS_SUBSCRIBE': 'JMS topic consumer  -> @JmsListener (topic)',
    'RV_SUBSCRIBE':  'Rendezvous consumer -> @JmsListener (after RV->JMS migration)',
    'FILE_POLLER':   'File poller         -> Spring Integration / WatchService',
    'TIMER':         'Timer trigger       -> @Scheduled',
    # BW6/BWCE: a BPEL receive with createInstance='yes' is the process's
    # invocable surface, exposed via the module's SCA service binding.
    'SERVICE_OPERATION': 'BPEL service operation -> @RestController / @Endpoint',
}

# Activity categories that reach outside the process boundary.
EXTERNAL_CALL_CATEGORIES = {
    'HTTP_REQUEST', 'SOAP_CALL', 'JDBC_QUERY', 'JDBC_UPDATE', 'JDBC_STORED_PROC',
    'JDBC_GENERAL', 'JMS_SEND', 'JMS_PUBLISH', 'JMS_REQUEST_REPLY', 'FTP_PUT',
    'FTP_GET', 'MAIL_SEND', 'RV_PUBLISH', 'FILE_READ', 'FILE_WRITE',
    # BW6/BWCE plugin families
    'KAFKA', 'NOSQL', 'CACHE', 'OBJECT_STORE', 'CLOUD_QUEUE', 'CLOUD_TOPIC',
    'SAAS_CALL', 'ERP_CALL', 'FILE_GENERAL',
}

# ─────────────────────────────────────────────────────────────
# Relationship semantics for impact traversal.
# weight = how strongly a change propagates across this edge (0..1),
# used for the decayed blast-radius risk score.
# ─────────────────────────────────────────────────────────────
REL_IMPACT_WEIGHTS: Dict[str, float] = {
    'USES_XSD': 1.0,
    'IMPORTS_SCHEMA': 1.0,
    'USES_WSDL': 1.0,
    'CALLS': 0.9,
    'CALLS_EXTERNAL': 0.5,
    'EXECUTES': 0.8,
    'CONTAINS': 0.9,
    'TRANSITIONS_TO': 0.4,
    'HANDLES_ERROR': 0.5,
    'REFERENCES': 0.7,
    'CONFIGURED_BY': 0.6,
    'CONNECTS_TO': 0.6,
    'EXPOSES': 0.8,
    'DEPENDS_ON': 0.7,
    'CONFIGURES': 0.6,
    'HAS_GROUP': 0.4,
    'BELONGS_TO': 0.1,
}

# Edges never walked during blast-radius expansion: they would drag in
# every artifact of a module and destroy signal.
IMPACT_EXCLUDED_RELS = {'BELONGS_TO'}

# ─────────────────────────────────────────────────────────────
# Domain synonyms for semantic search query expansion.
# ─────────────────────────────────────────────────────────────
SEARCH_SYNONYMS: Dict[str, list] = {
    'rest': ['http', 'endpoint', 'restcontroller', 'resource'],
    'http': ['rest', 'endpoint', 'url', 'uri'],
    'soap': ['wsdl', 'webservice', 'ws', 'envelope'],
    'queue': ['jms', 'destination', 'mq', 'topic'],
    'jms': ['queue', 'topic', 'destination', 'messaging'],
    'db': ['jdbc', 'database', 'sql', 'datasource', 'table'],
    'database': ['jdbc', 'sql', 'datasource', 'table', 'db'],
    'sql': ['jdbc', 'query', 'select', 'insert', 'update', 'database'],
    'error': ['fault', 'exception', 'catch', 'failure', 'rethrow'],
    'fault': ['error', 'exception', 'catch', 'failure'],
    'validation': ['validate', 'check', 'verify', 'constraint'],
    'transform': ['map', 'mapper', 'mapping', 'xslt', 'translate'],
    'mapping': ['mapper', 'transform', 'xslt', 'map'],
    'log': ['logging', 'audit', 'trace'],
    'schedule': ['timer', 'cron', 'poller', 'batch'],
    'file': ['ftp', 'sftp', 'directory', 'poller'],
    'auth': ['identity', 'credential', 'security', 'token'],
    'customer': ['client', 'party', 'account'],
    'order': ['purchase', 'sales'],
    'payment': ['billing', 'settlement', 'charge'],
    'credit': ['score', 'rating', 'bureau'],
}

SEARCH_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'for', 'on', 'is', 'are',
    'be', 'with', 'by', 'as', 'at', 'from', 'that', 'this', 'it', 'tibco',
    'com', 'plugin', 'core', 'pe', 'www', 'xmlns', 'xml', 'ns', 'tns',
    'where', 'which', 'what', 'how', 'does', 'do', 'find', 'show', 'me',
    'i', 'we', 'us', 'implemented', 'implementation',
}

# Complexity tier thresholds (score -> tier).
COMPLEXITY_TIERS = [
    (30.0, 'Critical'),
    (15.0, 'High'),
    (5.0, 'Medium'),
    (0.0, 'Low'),
]

SCHEMA_VERSION = '1.0.0'

# ─────────────────────────────────────────────────────────────
# Graph vocabulary and physical model
#
# One catalogue, consumed by `graph/schema.py`, which turns it into the Neo4j
# export schema and the validation configuration. This is the same arrangement
# the APEX and Oracle analyzers use, so all three now configure the shared
# engines in `analyzer_core.graph` rather than forking them.
# ─────────────────────────────────────────────────────────────
PROCESS_LABELS = {'Module', 'BWProcess', 'Activity', 'Group', 'ErrorHandler'}

SCHEMA_LABELS = {'XSD', 'Element', 'ComplexType', 'AESchema', 'DataTransformation'}

SERVICE_LABELS = {'Service', 'Operation'}

RESOURCE_LABELS = {'SharedResource', 'Adapter', 'System', 'GlobalVariable'}

ANALYSIS_LABELS = {'Issue', 'Recommendation', 'ExternalReference'}

KNOWN_LABELS = (PROCESS_LABELS | SCHEMA_LABELS | SERVICE_LABELS
                | RESOURCE_LABELS | ANALYSIS_LABELS)

STRUCTURAL_RELS = {'BELONGS_TO', 'EXECUTES', 'CONTAINS', 'HAS_GROUP',
                   'HANDLES_ERROR', 'CONFIGURED_BY', 'CONFIGURES'}

FLOW_RELS = {'TRANSITIONS_TO', 'CALLS', 'CALLS_EXTERNAL', 'EXPOSES'}

DEPENDENCY_RELS = {'USES_XSD', 'USES_WSDL', 'IMPORTS_SCHEMA', 'REFERENCES',
                   'DEPENDS_ON', 'CONNECTS_TO'}

ANALYSIS_RELS = {'HAS_ISSUE', 'HAS_RECOMMENDATION', 'AFFECTS'}

KNOWN_REL_TYPES = (STRUCTURAL_RELS | FLOW_RELS | DEPENDENCY_RELS | ANALYSIS_RELS)

# Without these the parse did not do its job.
REQUIRED_REL_TYPES = {'BELONGS_TO', 'EXECUTES', 'CONTAINS'}

# Present in a typical estate. Their absence is a warning, not an error: it can
# mean the estate is simple, or that the parser does not model them yet, and
# the artifact-coverage rule is what tells those two apart.
EXPECTED_REL_TYPES = {'USES_XSD', 'CALLS', 'TRANSITIONS_TO', 'HANDLES_ERROR',
                      'REFERENCES', 'EXPOSES', 'IMPORTS_SCHEMA'}

# Labels allowed to have no edges at all.
ORPHAN_TOLERANT_LABELS = {'System', 'GlobalVariable', 'DataTransformation',
                          'AESchema', 'ExternalReference'}

INT_FIELDS = {'activityCount', 'transitionCount', 'errorHandlerCount',
              'elementCount', 'complexTypeCount', 'simpleTypeCount',
              'importCount', 'operationCount', 'schemaRefCount', 'wsdlRefCount',
              'processVarCount', 'groupCount', 'order', 'fieldCount',
              'lineStart'}

FLOAT_FIELDS = {'complexityScore', 'confidence'}

BOOL_FIELDS = {'required', 'multiple', 'deployable', 'serviceSettable',
               'isStarter', 'hasEmbeddedCredential'}

COMPOSITE_CONSTRAINTS = [
    ('BWProcess', ['module', 'name']),
]

SECONDARY_INDEXES = [
    ('BWProcess', ['module']),
    ('BWProcess', ['tier']),
    ('BWProcess', ['entryType']),
    ('Activity', ['category']),
    ('Activity', ['processRef']),
    ('SharedResource', ['resourceType']),
    ('SharedResource', ['qualifiedName']),
    ('Adapter', ['technology']),
    ('XSD', ['module']),
    ('Issue', ['ruleId']),
    ('Issue', ['severity']),
]

FULLTEXT_INDEXES = [
    ('tibco_name_ft', ['BWProcess', 'Activity', 'Service', 'Operation',
                       'SharedResource', 'XSD'], ['name']),
    ('tibco_sql_ft', ['Activity'], ['sqlStatement']),
]

ID_PATTERN = re.compile(r'^[A-Za-z0-9_.:#$/@ -]+$')

# Blast radius: how strongly a change travels along each edge.
REL_IMPACT_WEIGHTS = {
    'CALLS': 1.0,
    'EXECUTES': 0.9,
    'EXPOSES': 0.9,
    'REFERENCES': 0.8,
    'USES_XSD': 0.7,
    'USES_WSDL': 0.7,
    'CONFIGURED_BY': 0.7,
    'IMPORTS_SCHEMA': 0.6,
    'TRANSITIONS_TO': 0.6,
    'HAS_GROUP': 0.5,
    'HANDLES_ERROR': 0.5,
    'CONTAINS': 0.4,
    'CONFIGURES': 0.4,
    'CONNECTS_TO': 0.3,
}

IMPACT_EXCLUDED_RELS = {'BELONGS_TO', 'HAS_ISSUE', 'AFFECTS',
                        'HAS_RECOMMENDATION'}

MULTIPLIERS = {
    'BWProcess': 2.5, 'Service': 2.2, 'Operation': 2.0, 'Activity': 1.0,
    'SharedResource': 1.0, 'XSD': 0.8, 'Adapter': 0.6, 'Group': 0.4,
    'ErrorHandler': 0.4, 'Element': 0.2, 'ComplexType': 0.2,
    'Issue': 0.0, 'Recommendation': 0.0,
}

# Finding severities, weakest first, so a filter is an index comparison.
SEVERITY_ORDER = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
