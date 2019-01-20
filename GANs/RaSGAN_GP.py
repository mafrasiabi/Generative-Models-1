import tensorflow as tf
from models.generative.ops import *
from models.generative.utils import *


class RaSGAN_GP:
	def __init__(self, data, z_dim, use_bn, alpha, beta_1, beta_2, n_critic, gp_coeff, learning_rate, model_name):

		self.model_name = model_name

		# Input data variables.
		self.image_height = data.training.patch_h
		self.image_width = data.training.patch_w
		self.image_channels = data.training.n_channels
		self.batch_size = data.training.batch_size

		# Latent space dimensions.
		self.z_dim = z_dim

		# Network details
		self.use_bn = use_bn
		self.alpha = alpha

		# Training parameters
		self.n_critic = n_critic
		self.gp_coeff = gp_coeff
		self.beta_1 = beta_1
		self.beta_2 = beta_2
		self.learning_rate = learning_rate

		self.build_model()


	def discriminator(self, images, reuse):
		with tf.variable_scope('discriminator', reuse=reuse):
			# Input Shape: (None, 28, 28, 1)
			# Padding = 'Same' -> H_new = H_old // Stride

			# Conv layer.
			net = tf.layers.conv2d(inputs=images, filters=64, kernel_size=(5,5), strides=(2, 2), padding='same', kernel_initializer=tf.contrib.layers.xavier_initializer_conv2d())
			net = leakyReLU(net, alpha)
			# Shape: (None, 16, 16, 64)

			# Conv layer.
			net = tf.layers.conv2d(inputs=net, filters=128, kernel_size=(5,5), strides=(2, 2), padding='same', kernel_initializer=tf.contrib.layers.xavier_initializer_conv2d())
			net = tf.layers.batch_normalization(net, training=True)
			net = leakyReLU(net, alpha)
			# Shape: (None, 8, 8, 128)

			net = tf.layers.flatten(net, name='flatten')
			# Shape: (None, 8*8*128)

			# Dense.
			net = tf.layers.dense(net, 1024, activation=None)
			net = tf.layers.batch_normalization(net, training=True)
			net = leakyReLU(net, alpha)
			# Shape: (None, 1024)

			# Dense
			logits = tf.layers.dense(net, 1, activation=None)
			# Shape: (None, 1)
			output = tf.nn.sigmoid(logits)

		return output, logits

	def generator(self, z_input, reuse, is_train):
		with tf.variable_scope('generator', reuse=reuse):
			# Dense layer.
			net = tf.layers.dense(inputs=z_input, units=1024, activation=None)
			net = tf.layers.batch_normalization(net, training=is_train)
			net = leakyReLU(net, alpha)
			# Shape: (None, 1024)

			# Dense layer.
			net = tf.layers.dense(inputs=net, units=128*7*7, activation=None)
			net = tf.layers.batch_normalization(net, training=is_train)
			net = leakyReLU(net, alpha)
			# Shape: (None, 128*7*7)

			net = tf.reshape(net, (-1, 7, 7, 128))
			# Shape: (None, 7, 7, 128)

			# Conv
			net = tf.layers.conv2d_transpose(inputs=net, filters=128, kernel_size=(2,2), strides=(2,2), padding='same', kernel_initializer=tf.contrib.layers.xavier_initializer_conv2d())
			net = tf.layers.batch_normalization(net, training=is_train)
			net = leakyReLU(net, alpha)
			# Shape: (None, 14, 14, 128)

			# Conv
			net = tf.layers.conv2d(inputs=net, filters=128, kernel_size=(5,5), strides=(1,1), padding='same', kernel_initializer=tf.contrib.layers.xavier_initializer_conv2d())
			net = tf.layers.batch_normalization(net, training=is_train)
			net = leakyReLU(net, alpha)
			# Shape: (None, 14, 14, 128)

			# Conv
			logits = tf.layers.conv2d_transpose(inputs=net, filters=out_channel_dim, kernel_size=(2,2), strides=(2,2), padding='same', kernel_initializer=tf.contrib.layers.xavier_initializer_conv2d())
			# Shape: (None, 28, 28, 1)
			output = tf.nn.sigmoid(logits)

		return output


	def model_inputs(self):
		real_images = tf.placeholder(dtype=tf.float32, shape=(None, self.image_width, self.image_height, self.image_channels), name='real_images')
		z_input = tf.placeholder(dtype=tf.float32, shape=(None, self.z_dim), name='z_input')
		learning_rate = tf.placeholder(dtype=tf.float32, name='learning_rate')
		return real_images, z_input, learning_rate


	def loss(self):
		logits_diff_real_fake = self.logits_real - tf.reduce_mean(self.logits_fake, axis=0, keepdims=True)
		logits_diff_fake_real = self.logits_fake - tf.reduce_mean(self.logits_real, axis=0, keepdims=True)

		# Calculating X hat.
		epsilon = tf.random.uniform(shape=(self.batch_size, 1, 1, 1), minval=0.0, maxval=1.0, dtype=tf.float32, name='epsilon')
		x_gp = self.real_images*(1-epsilon) + self.fake_images*epsilon
		output_gp, logits_gp = self.discriminator(x_gp, True)

		# Calculating Gradient Penalty.
		grad_gp = tf.gradients(logits_gp, x_gp)
		l2_grad_gp = tf.sqrt(tf.reduce_sum(tf.square(grad_gp), axis=[1, 2, 3]))
		grad_penalty= tf.reduce_sum(tf.square(l2_grad_gp-1.0))

		# Discriminator loss.
		loss_dis_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=logits_diff_real_fake, labels=tf.ones_like(self.logits_fake)))
		loss_dis_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=logits_diff_fake_real, labels=tf.zeros_like(self.logits_fake)))
		loss_dis = loss_dis_real + loss_dis_fake + (self.gp_coeff*grad_penalty)

		# Generator loss.
		loss_gen_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=logits_diff_fake_real, labels=tf.ones_like(self.logits_fake)))
		loss_gen_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=logits_diff_real_fake, labels=tf.zeros_like(self.logits_fake)))
		loss_gen = loss_gen_real + loss_gen_fake

		return loss_dis, loss_gen


	def optimization(self):
		trainable_variables = tf.trainable_variables()
		generator_variables = [variable for variable in trainable_variables if variable.name.startswith('generator')]
		discriminator_variables = [variable for variable in trainable_variables if variable.name.startswith('discriminator')]

		# Handling Batch Normalization.
		with tf.control_dependencies(tf.get_collection(tf.GraphKeys.UPDATE_OPS)):
			train_discriminator = tf.train.AdamOptimizer(self.learning_rate_input, self.beta_1, self.beta_2).minimize(self.loss_dis, var_list=discriminator_variables)
			train_generator = tf.train.AdamOptimizer(self.learning_rate_input, self.beta_1, self.beta_2).minimize(self.loss_gen, var_list=generator_variables)
		return train_discriminator, train_generator


	def build_model(self):
		# Inputs.
		self.real_images, self.z_input, self.learning_rate_input = self.model_inputs()

		# Neural Network Generator and Discriminator.
		self.fake_images = self.generator(self.z_input, reuse=False, is_train=True)

		self.output_fake, self.logits_fake = self.discriminator(images=self.fake_images, reuse=False) 
		self.output_real, self.logits_real = self.discriminator(images=self.real_images, reuse=True)

		# Losses.
		self.loss_dis, self.loss_gen = self.loss()

		# Optimizers.
		self.train_discriminator, self.train_generator = self.optimization()

		self.output_gen = self.generator(self.z_input, reuse=True, is_train=False)


	def train(self, epochs, data_out_path, data, show_epochs=100, print_epochs=10, n_images=10):
		run_epochs = 0    
		losses = list()
		saver = tf.train.Saver()

		img_storage, latent_storage, checkpoints = setup_output(show_epochs, epochs, data, n_images, self.z_dim, data_out_path, self.model_name)

		with tf.Session() as session:
			session.run(tf.global_variables_initializer())
			for epoch in range(1, epochs+1):
				for batch_images, batch_labels in data.training:
					# Inputs.
					z_batch = np.random.uniform(low=-1., high=1., size=(self.batch_size, self.z_dim))
					feed_dict = {self.z_input:z_batch, self.real_images:batch_images, self.learning_rate_input: self.learning_rate}

					# Update critic.
					session.run(self.train_discriminator, feed_dict=feed_dict)

					# Update generator after n_critic updates from discriminator.
					if run_epochs%self.n_critic :
						session.run(self.train_generator, feed_dict=feed_dict)

					# Print losses and Generate samples.
					if run_epochs % print_epochs == 0:
						feed_dict = {self.z_input:z_batch, self.real_images:batch_images}
						epoch_loss_dis, epoch_loss_gen = session.run([self.loss_dis, self.loss_gen], feed_dict=feed_dict)
						losses.append((epoch_loss_dis, epoch_loss_gen))
						print('Epochs %s/%s: Generator Loss: %s. Discriminator Loss: %s' % (epoch, epochs, np.round(epoch_loss_gen, 4), np.round(epoch_loss_dis, 4)))
					if run_epochs % show_epochs == 0:
						gen_samples, sample_z = show_generated(session=session, z_input=self.z_input, z_dim=self.z_dim, output_fake=self.output_gen, n_images=n_images, dim=30)
						img_storage[run_epochs//show_epochs] = gen_samples
						latent_storage[run_epochs//show_epochs] = sample_z
						saver.save(sess=session, save_path=checkpoints, global_step=run_epochs)

					run_epochs += 1
				data.training.reset()

		return losses

	

