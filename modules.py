import tensorflow as tf
from convolutional import Conv1D


class Conv:
    def __init__(self, in_channels, out_channels, kernel_size=3, dilation=1, causal=True, scope='Conv'):
        with tf.variable_scope(scope):
            self._scope = scope
            self._causal = causal

            if self._causal:
                self._padding = dilation * (kernel_size - 1)
            else:
                self._padding = dilation * (kernel_size - 1) // 2

            self._conv = Conv1D(filters=out_channels, 
                                        kernel_size=kernel_size,
                                        dilation_rate=dilation,
                                        padding='valid',
                                        kernel_initializer=tf.initializers.he_uniform(),
                                        bias_initializer=tf.initializers.zeros())
            
            

    def forward(self, tensor):
        with tf.variable_scope(self._scope):
                padded_tensor = tf.pad(tensor, ((0, 0), (self._padding, self._padding), (0, 0)))
                out = self._conv(padded_tensor)

                if self._causal and self._padding is not 0:
                    out = out[:, :-self._padding]

                return out

    def __call__(self, tensor):
        return self.forward(tensor)


class ZeroConv1d:
    def __init__(self, in_channel, out_channel, scope='ZeroConv1d'):
        with tf.variable_scope(scope):
            self._scope = scope
            self._conv = Conv1D(filters=out_channel, 
                                          kernel_size=1, 
                                          padding='valid', 
                                          kernel_initializer=tf.initializers.zeros(), 
                                          bias_initializer=tf.initializers.zeros())

            self._scale = tf.get_variable('scale', shape=[1, 1, out_channel], initializer=tf.initializers.zeros())

    
    def forward(self, x):
        with tf.variable_scope(self._scope):
                out = self._conv(x)
                out = out * tf.exp(self._scale * 3)
                return out

    def __call__(self, x):
        return self.forward(x)
            

class ResBlock:
    def __init__(self, in_channels, out_channels, skip_channels, kernel_size, dilation,
                 cin_channels=None, local_conditioning=True, causal=False, scope='ResBlock'):
        
        with tf.variable_scope(scope):
            self._scope = scope
            self._causal = causal
            self._local_conditioning = local_conditioning
            self._cin_channels = cin_channels
            self._skip = True if skip_channels is not None else False

            self._filter_conv = Conv(in_channels, out_channels, kernel_size, dilation, causal, scope='Conv_filter')
            self._gate_conv = Conv(in_channels, out_channels, kernel_size, dilation, causal, scope='Conv_gate')
            self._res_conv = Conv1D(filters=out_channels, 
                                              kernel_size=1,
                                              kernel_initializer=tf.initializers.he_uniform(),
                                              bias_initializer=tf.initializers.zeros())

            if self._skip:
                self._skip_conv = Conv1D(filters=skip_channels, 
                                                   kernel_size=1, 
                                                   kernel_initializer=tf.initializers.he_uniform(),
                                                   bias_initializer=tf.initializers.zeros())

            if self._local_conditioning:
                self._filter_conv_c = Conv1D(filters=out_channels, 
                                                       kernel_size=1, 
                                                       kernel_initializer=tf.initializers.he_uniform(),
                                                       bias_initializer=tf.initializers.zeros())
                
                self._gate_conv_c = Conv1D(filters=out_channels, 
                                                     kernel_size=1,
                                                     kernel_initializer=tf.initializers.he_uniform(),
                                                     bias_initializer=tf.initializers.zeros())

    def forward(self, tensor, c=None):
        with tf.variable_scope(self._scope):
                h_filter = self._filter_conv(tensor)
                h_gate = self._gate_conv(tensor)

                if self._local_conditioning:
                    h_filter += self._filter_conv_c(c)
                    h_gate += self._gate_conv_c(c)

                out = tf.tanh(h_filter) * tf.sigmoid(h_gate)

                res = self._res_conv(out)
                skip = self._skip_conv(out) if self._skip else None
                return (tensor + res) * tf.sqrt(0.5), skip

    def __call__(self, tensor, c=None):
        return self.forward(tensor, c)


class WaveNet:
    def __init__(self, in_channels=1, out_channels=2, num_blocks=1, num_layers=6,
                 residual_channels=256, gate_channels=256, skip_channels=256,
                 kernel_size=3, cin_channels=80, causal=True, scope='WaveNet'):

        with tf.variable_scope(scope):
            self._scope = scope
            self._skip = True if skip_channels is not None else False

            self._front_conv = Conv(in_channels, residual_channels, 3, causal=causal, scope='Conv_front')
            # self._front_conv = tf.nn.relu(self._front_conv)

            self._res_blocks = []

            for b in range(num_blocks):
                for n in range(num_layers):
                    self._res_blocks.append(ResBlock(residual_channels, gate_channels, skip_channels,
                                                     kernel_size, dilation=kernel_size ** n,
                                                     cin_channels=cin_channels, local_conditioning=True,
                                                     causal=causal, scope='ResBlock_%d_%d' % (b, n)))

            last_channels = skip_channels if self._skip else residual_channels

            self._final_conv = Conv(last_channels, last_channels, 1, causal=causal, scope='Conv_final')
            self._final_zero_conv = ZeroConv1d(last_channels, out_channels)

    def forward(self, x, c=None):
        with tf.variable_scope(self._scope):
                h = self._front_conv(x)
                h = tf.nn.relu(h)

                skip = []
                for i, f in enumerate(self._res_blocks):
                    if self._skip:
                        h, s = f(h, c)
                        skip.append(s)
                    else:
                        h, _ = f(h, c)

                if self._skip:
                    out = tf.add_n(skip)
                    out = tf.nn.relu(out)
                    out = self._final_conv(out)
                    out = tf.nn.relu(out)
                    out = self._final_zero_conv(out)
                else:
                    out = tf.nn.relu(h)
                    out = self._final_conv(out)
                    out = tf.nn.relu(out)
                    out = self._final_zero_conv(out)
                return out

    def __call__(self, x, c=None):
        return self.forward(x, c)


