from eventlet import wsgi, monkey_patch
from adistools.adisconfig import adisconfig
from adistools.log import Log
from pika import BlockingConnection, PlainCredentials, ConnectionParameters
from json import loads, dumps
from time import sleep, time
from uuid import uuid4

monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO

import functools

class socketio_dispatcher:
    name="sicken-socketio_dispatcher"

    def __init__(self, application, socketio):
        self.application=application
        self.socketio=socketio

        self.config=adisconfig('/opt/adistools/configs/honeypot_proxy-honeypot_proxy.yaml')
        self.log=Log(
            parent=self,
            rabbitmq_host=self.config.rabbitmq.host,
            rabbitmq_port=self.config.rabbitmq.port,
            rabbitmq_user=self.config.rabbitmq.user,
            rabbitmq_passwd=self.config.rabbitmq.password,
            debug=self.config.log.debug,
            )


        self.application.config['SECRET_KEY'] = self.config.socketio.secret


        self._requests={}
        self._proxies={}
        self._clients={}

        self.bind_socketio_events()

    def start(self):
        self.socketio.start_background_task(target=self._proxy_checker)
        self.socketio.start_background_task(target=self._client_checker)
        self.socketio.run(self.application, host=self.config.socketio.host, port=self.config.socketio.port)

    def _find_proxy(self):
        for proxy in self._proxies:
            if self._proxies[proxy]['last_ping']:
                if time() - self._proxies[proxy]['last_ping']<2:
                    return self._proxies[proxy]

    def _proxy_checker(self):
        while True:
            try:
                for proxy in self._proxies:
                    if self._proxies[proxy]['last_ping']:
                        if time() - self._proxies[proxy]['last_ping']>=2:
                            print('removing proxy', self._proxies[proxy]['sid'])
                            del self._proxies[proxy]
                self.socketio.sleep(0.1)
            except RuntimeError:
                pass

    def _client_checker(self):
        while True:
            try:
                for client in self._clients:
                    if self._clients[client]['last_ping']:
                        if time() - self._clients[client]['last_ping']>=2:
                            print('removing client', self._clients[client]['sid'])
                            del self._clients[client]
                self.socketio.sleep(0.1)
            except RuntimeError:
                pass

    def _connect(self):
        print("connect", request.sid)

    def _proxy_ping(self):
        if request.sid in self._proxies:
            self._proxies[request.sid]['last_ping']=time()
            print('proxy_ping')
    
    def _client_ping(self):
        if request.sid in self._clients:
            self._clients[request.sid]['last_ping']=time()
            print('client_ping')

    def _proxy_connect(self):
        self._proxies[request.sid]={"sid": request.sid, "last_ping": None}

        print('proxy_connect', request.sid)

    def _client_connect(self):
        self._clients[request.sid]={"sid": request.sid, "last_ping": None}

        print('client_connect', request.sid)


    def _build_response_message(self,request_uuid, request_url, status, message=None, content=None):
        return {
            "request_uuid": request_uuid,
            "request_url": request_url,
            "status": status,
            "message": message,
            "content": content
        }

    def _client_request(self, message):
        self._requests[message['request_uuid']]={
            "request_uuid": message['request_uuid'],
            "request_url": message['request_url'],
            "request_status": "waiting",
            "client_sid": request.sid
        }

        proxy=self._find_proxy()
        if proxy:
            self.socketio.emit('request', message, to=proxy['sid'])
        else:
            self.socketio.emit(
                'response',
                 self._build_response_message(
                    request_uuid=message['request_uuid'],
                    request_url=message['request_url'],
                    status="Error",
                    message="No avaiable proxy servers"
                 ),
                 to=request.sid)
            
    def _proxy_response(self, message):
        if message['request_uuid'] in self._requests:
            self.socketio.emit(
                'response',
                self._build_response_message(
                    request_uuid=message['request_uuid'],
                    request_url=message['request_url'],
                    status="Success",
                    message="Success",
                    content=message['content']
                    )
                )

    def bind_socketio_events(self):
        self.socketio.on_event('connect', self._connect, namespace="/")
        self.socketio.on_event('proxy_connect', self._proxy_connect, namespace="/")
        self.socketio.on_event('client_connect', self._client_connect, namespace="/")

        self.socketio.on_event('proxy_ping', self._proxy_ping, namespace="/")
        self.socketio.on_event('client_ping', self._client_ping, namespace="/")

        self.socketio.on_event('client_request', self._client_request, namespace="/")
        self.socketio.on_event('proxy_response', self._proxy_response, namespace="/")



if __name__=="__main__":
    app = Flask(__name__)
    socketio = SocketIO(
        app,
        cors_allowed_origins="*")

    socketio_dispatcher=socketio_dispatcher(app, socketio)
    socketio_dispatcher.start()
